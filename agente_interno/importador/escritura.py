"""Escribe una carga en la base de datos en una sola transacción.

Catálogo, categorías y proveedores se actualizan conservando sus identificadores. Ventas, compras, devoluciones,
precios, movimientos e inventario del negocio se sustituyen por completo: el agente ve los datos anteriores hasta
que la transacción termina y nunca un estado a medias.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg

from .motor import CONFIG_DEFECTO, Carga, Compra, Devolucion, Ticket


def tasas_existentes(conn: psycopg.Connection) -> dict[date, Decimal]:
    return dict(conn.execute("select fecha, usd_cup from public.tasas_cambio").fetchall())


def negocio(conn: psycopg.Connection, nombre: str | None) -> tuple[int | None, str]:
    """Devuelve (id, nombre). Sin nombre, usa el único negocio de la base de datos."""
    if nombre:
        fila = conn.execute("select id from public.negocios where nombre = %s", (nombre,)).fetchone()
        return (fila[0] if fila else None), nombre
    filas = conn.execute("select id, nombre from public.negocios order by id").fetchall()
    if len(filas) == 1:
        return filas[0]
    if not filas:
        raise ValueError("La base de datos no tiene ningún negocio: indica su nombre con --negocio.")
    raise ValueError("La base de datos tiene varios negocios: indica cuál con --negocio "
                     f"({', '.join(n for _, n in filas)}).")


def _ids(conn: psycopg.Connection, tabla: str, n: int) -> list[int]:
    if n == 0:
        return []
    return [f[0] for f in conn.execute(
        "select nextval(pg_get_serial_sequence(%s, 'id')) from generate_series(1, %s)", (f"public.{tabla}", n)).fetchall()]


def _copiar(conn: psycopg.Connection, tabla: str, columnas: tuple[str, ...], filas) -> int:
    """COPY a una tabla temporal y de ahí a la definitiva (COPY no se admite en tablas con RLS para roles sin BYPASSRLS)."""
    cols = ", ".join(columnas)
    tmp = "_imp_" + tabla.split(".")[-1]
    conn.execute(f"create temp table {tmp} on commit drop as select {cols} from {tabla} with no data")
    n = 0
    with conn.cursor().copy(f"copy {tmp} ({cols}) from stdin") as cp:
        for f in filas:
            cp.write_row(f)
            n += 1
    sobre = "overriding system value " if "id" in columnas else ""
    conn.execute(f"insert into {tabla} ({cols}) {sobre}select {cols} from {tmp}")
    return n


def escribir(conn: psycopg.Connection, carga: Carga, nombre_negocio: str | None) -> dict[str, int]:
    with conn.transaction():
        conn.execute("set local statement_timeout = 0")
        neg_id, nombre = negocio(conn, nombre_negocio)
        if neg_id is None:
            neg_id = conn.execute("insert into public.negocios (nombre) values (%s) returning id", (nombre,)).fetchone()[0]
        conn.execute("select pg_advisory_xact_lock(hashtext('importador'), %s::int)", (neg_id,))

        # Configuración de categorías (tabla global del esquema agente): las del archivo mandan; las demás, por defecto.
        for cat in sorted({p.categoria for p in carga.productos.values()} - set(carga.config_categorias)):
            conn.execute("insert into agente.config_categoria (nombre, linea, plazo_dias, dias_stock_minimo, basico) "
                         "values (%s, %s, %s, %s, %s) on conflict (nombre) do nothing",
                         (cat, CONFIG_DEFECTO["linea"], CONFIG_DEFECTO["plazo_dias"], CONFIG_DEFECTO["dias_stock_minimo"],
                          CONFIG_DEFECTO["basico"]))
        for cat, cfg in carga.config_categorias.items():
            conn.execute("insert into agente.config_categoria (nombre, linea, plazo_dias, dias_stock_minimo, basico) "
                         "values (%s, %s, %s, %s, %s) on conflict (nombre) do update set linea = excluded.linea, "
                         "plazo_dias = excluded.plazo_dias, dias_stock_minimo = excluded.dias_stock_minimo, basico = excluded.basico",
                         (cat, cfg["linea"], cfg["plazo_dias"], cfg["dias_stock_minimo"], cfg["basico"]))

        # Categorías (dos niveles: categoría → subcategoría).
        cats = {(padre, n): i for i, n, padre in conn.execute(
            "select id, nombre, categoria_padre_id from public.categorias where negocio_id = %s", (neg_id,)).fetchall()}

        def categoria(nombre_cat: str, padre: int | None) -> int:
            if (padre, nombre_cat) not in cats:
                cats[(padre, nombre_cat)] = conn.execute(
                    "insert into public.categorias (negocio_id, nombre, categoria_padre_id) values (%s, %s, %s) returning id",
                    (neg_id, nombre_cat, padre)).fetchone()[0]
            return cats[(padre, nombre_cat)]

        # Productos: se actualizan por SKU; los que ya no están en los archivos quedan inactivos.
        existentes = dict(conn.execute("select sku, id from public.productos where negocio_id = %s", (neg_id,)).fetchall())
        prod_id: dict[str, int] = {}
        for p in carga.productos.values():
            cat_id = categoria(p.subcategoria, categoria(p.categoria, None))
            valores = (p.nombre, cat_id, p.unidad, p.stock_minimo, p.activo, p.alta)
            if p.sku in existentes:
                conn.execute("update public.productos set nombre = %s, categoria_id = %s, unidad = %s, stock_minimo = %s, "
                             "activo = %s, creado_en = %s where id = %s", (*valores, existentes[p.sku]))
                prod_id[p.sku] = existentes[p.sku]
            else:
                prod_id[p.sku] = conn.execute(
                    "insert into public.productos (nombre, categoria_id, unidad, stock_minimo, activo, creado_en, negocio_id, sku) "
                    "values (%s, %s, %s, %s, %s, %s, %s, %s) returning id", (*valores, neg_id, p.sku)).fetchone()[0]
        retirados = [i for sku, i in existentes.items() if sku not in prod_id]
        if retirados:
            conn.execute("update public.productos set activo = false where id = any(%s)", (retirados,))

        # Proveedores.
        prov = dict(conn.execute("select nombre, id from public.proveedores where negocio_id = %s", (neg_id,)).fetchall())
        for c in carga.compras:
            if c.proveedor not in prov:
                prov[c.proveedor] = conn.execute("insert into public.proveedores (negocio_id, nombre) values (%s, %s) returning id",
                                                 (neg_id, c.proveedor)).fetchone()[0]

        # Se sustituye todo lo transaccional del negocio.
        for q in (
            "delete from public.devoluciones d using public.lineas_venta lv, public.ventas v "
            "where d.linea_venta_id = lv.id and lv.venta_id = v.id and v.negocio_id = %(n)s",
            "delete from public.pagos x using public.ventas v where x.venta_id = v.id and v.negocio_id = %(n)s",
            "delete from public.lineas_venta x using public.ventas v where x.venta_id = v.id and v.negocio_id = %(n)s",
            "delete from public.ventas where negocio_id = %(n)s",
            "delete from public.lineas_compra x using public.compras c where x.compra_id = c.id and c.negocio_id = %(n)s",
            "delete from public.compras where negocio_id = %(n)s",
            "delete from public.movimientos_inventario x using public.productos p where x.producto_id = p.id and p.negocio_id = %(n)s",
            "delete from public.precios_producto x using public.productos p where x.producto_id = p.id and p.negocio_id = %(n)s",
            "delete from public.inventario x using public.productos p where x.producto_id = p.id and p.negocio_id = %(n)s",
        ):
            conn.execute(q, {"n": neg_id})

        for t, i in zip(carga.tickets, _ids(conn, "ventas", len(carga.tickets))):
            t.id = i
        lineas = [l for t in carga.tickets for l in t.lineas]
        for l, i in zip(lineas, _ids(conn, "lineas_venta", len(lineas))):
            l.id = i
        for c, i in zip(carga.compras, _ids(conn, "compras", len(carga.compras))):
            c.id = i
        for d, i in zip(carga.devoluciones, _ids(conn, "devoluciones", len(carga.devoluciones))):
            d.id = i

        n = {}
        n["ventas"] = _copiar(conn, "public.ventas", ("id", "negocio_id", "numero", "canal", "fecha", "estado", "tasa_usd_cup",
                                                      "total_usd", "total_cup", "anulada_en", "motivo_anulacion"),
                              ((t.id, neg_id, t.numero, t.canal, t.fecha, t.estado, t.tasa, t.total_usd, t.total_cup,
                                t.anulada_en, t.motivo_anulacion) for t in carga.tickets))
        n["lineas_venta"] = _copiar(conn, "public.lineas_venta", ("id", "venta_id", "producto_id", "cantidad", "precio_unitario_usd",
                                                                  "precio_unitario_cup", "coste_unitario_usd"),
                                    ((l.id, t.id, prod_id[l.sku], l.cantidad, l.precio_usd, l.precio_cup, l.coste_usd)
                                     for t in carga.tickets for l in t.lineas))
        n["pagos"] = _copiar(conn, "public.pagos", ("venta_id", "moneda", "metodo", "importe"),
                             ((t.id, mon, met, imp) for t in carga.tickets for (mon, met), imp in t.pagos.items()))
        n["devoluciones"] = _copiar(conn, "public.devoluciones", ("id", "linea_venta_id", "fecha", "cantidad", "motivo",
                                                                  "reembolso_usd", "reingresa_stock"),
                                    ((d.id, d.linea.id, d.fecha, d.cantidad, d.motivo, d.reembolso_usd, d.reingresa)
                                     for d in carga.devoluciones))
        n["compras"] = _copiar(conn, "public.compras", ("id", "negocio_id", "proveedor_id", "fecha", "estado", "total_usd"),
                               ((c.id, neg_id, prov[c.proveedor], c.fecha, c.estado, c.total_usd) for c in carga.compras))
        n["lineas_compra"] = _copiar(conn, "public.lineas_compra", ("compra_id", "producto_id", "cantidad", "coste_unitario_usd"),
                                     ((c.id, prod_id[s], q, cu) for c in carga.compras for s, q, cu in c.lineas))

        def referencia(m):
            r = m.referencia
            if isinstance(r, Ticket):
                return "venta", r.id
            if isinstance(r, Compra):
                return "compra", r.id
            if isinstance(r, Devolucion):
                return "devolucion", r.id
            return "ajuste", None

        n["movimientos"] = _copiar(conn, "public.movimientos_inventario",
                                   ("producto_id", "fecha", "tipo", "cantidad", "referencia_tipo", "referencia_id"),
                                   ((prod_id[m.sku], m.fecha, m.tipo, m.cantidad, *referencia(m)) for m in carga.movimientos))
        n["precios"] = _copiar(conn, "public.precios_producto", ("producto_id", "precio_usd", "vigente_desde", "vigente_hasta"),
                               ((prod_id[sku], v, desde, hasta) for sku, lista in carga.precios.items() for v, desde, hasta in lista))
        inventario = [(prod_id[sku], s, c, f) for sku, (s, c, f) in carga.inventario.items()]
        inventario += [(i, 0, 0, carga.ahora) for i in retirados]
        n["inventario"] = _copiar(conn, "public.inventario", ("producto_id", "stock_actual", "coste_medio_usd", "actualizado_en"),
                                  inventario)

        for d, (v, fuente) in sorted(carga.tasas.items()):
            conn.execute("insert into public.tasas_cambio (fecha, usd_cup, fuente) values (%s, %s, %s) "
                         "on conflict (fecha) do update set usd_cup = excluded.usd_cup, fuente = excluded.fuente, obtenida_en = now()",
                         (d, v, fuente))
        n["tasas"] = len(carga.tasas)

        # Categorías que se han quedado vacías (primero subcategorías, después categorías).
        for _ in range(2):
            conn.execute("delete from public.categorias c where c.negocio_id = %s "
                         "and not exists (select 1 from public.productos p where p.categoria_id = c.id) "
                         "and not exists (select 1 from public.categorias h where h.categoria_padre_id = c.id)", (neg_id,))
        n["negocio_id"] = neg_id
        return n
