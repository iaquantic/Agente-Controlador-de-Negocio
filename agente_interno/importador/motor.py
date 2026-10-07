"""Convierte los archivos leídos en la carga completa de la base de datos, sin tocarla.

La carpeta del cliente es la fuente de verdad: cada importación reconstruye las ventas, compras, devoluciones,
precios e inventario del negocio a partir de todos los archivos. Así importar dos veces da el mismo resultado y
corregir un dato es tan simple como volver a exportar el archivo.

Inventario: el stock y el coste medio se recalculan en orden cronológico con todas las entradas y salidas.
Los conteos (archivo de inventario o columna de stock del catálogo) son la verdad en su fecha: el stock anterior al
primer conteo se reconstruye hacia atrás ("saldo inicial") y las diferencias posteriores quedan como ajustes.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from . import lectura as L
from .lectura import ZONA, ErrorDato, Fila, Tabla

CENT = Decimal("0.01")
DIEZMIL = Decimal("0.0001")
CERO = Decimal(0)
SIN_CATEGORIA = "Sin categoría"
SIN_PROVEEDOR = "Sin proveedor"
CONFIG_DEFECTO = {"linea": "Mercado", "plazo_dias": 7, "dias_stock_minimo": 7, "basico": False}


def r2(x: Decimal) -> Decimal:
    return x.quantize(CENT, ROUND_HALF_UP)


def r4(x: Decimal) -> Decimal:
    return x.quantize(DIEZMIL, ROUND_HALF_UP)


# Informe ---------------------------------------------------------------------------------------------------

@dataclass
class Informe:
    errores: list[tuple[str, str]] = field(default_factory=list)       # (dónde, qué): filas que no se importan
    avisos_archivo: list[str] = field(default_factory=list)
    _avisos: dict[str, list] = field(default_factory=dict)             # clave → [mensaje, cuántos, ejemplos]
    resumen: dict[str, object] = field(default_factory=dict)

    def error(self, donde: str, mensaje: str) -> None:
        self.errores.append((donde, mensaje))

    def aviso(self, clave: str, mensaje: str, ejemplo: str | None = None) -> None:
        a = self._avisos.setdefault(clave, [mensaje, 0, []])
        a[1] += 1
        if ejemplo and len(a[2]) < 5 and ejemplo not in a[2]:
            a[2].append(ejemplo)

    @property
    def avisos(self) -> list[str]:
        salida = list(self.avisos_archivo)
        for mensaje, n, ejemplos in self._avisos.values():
            salida.append(f"{mensaje} ({n})" + (f": {', '.join(ejemplos)}" + ("…" if n > len(ejemplos) else "") if ejemplos else ""))
        return salida

    def texto(self, max_errores: int = 40) -> str:
        lineas = []
        if self.resumen:
            lineas.append("Resumen:")
            lineas += [f"  · {k}: {v}" for k, v in self.resumen.items()]
        if self.avisos:
            lineas.append(f"Avisos ({len(self.avisos)}):")
            lineas += [f"  ! {a}" for a in self.avisos]
        if self.errores:
            lineas.append(f"Errores ({len(self.errores)} filas no se pueden importar):")
            lineas += [f"  ✗ {d}: {m}" for d, m in self.errores[:max_errores]]
            if len(self.errores) > max_errores:
                lineas.append(f"  … y {len(self.errores) - max_errores} más")
        else:
            lineas.append("Sin errores.")
        return "\n".join(lineas)


# Modelo ----------------------------------------------------------------------------------------------------

@dataclass
class Producto:
    sku: str
    nombre: str
    categoria: str
    subcategoria: str
    unidad: str = "unidad"
    stock_minimo: Decimal = CERO
    activo: bool = True
    precio: tuple[Decimal, str] | None = None       # (valor, moneda)
    coste: tuple[Decimal, str] | None = None
    alta: datetime | None = None
    automatico: bool = False                         # creado porque aparece en ventas/compras y no en el catálogo


@dataclass
class Linea:
    sku: str
    cantidad: Decimal
    precio_usd: Decimal
    precio_cup: Decimal
    coste_usd: Decimal | None                        # None = se calcula con el coste medio en el momento de la venta
    devuelta: Decimal = CERO
    id: int | None = None


@dataclass
class Ticket:
    numero: str
    fecha: datetime
    canal: str
    estado: str
    tasa: Decimal
    lineas: list[Linea]
    pagos: dict[tuple[str, str], Decimal]            # (moneda, método) → importe en esa moneda
    anulada_en: datetime | None = None
    motivo_anulacion: str | None = None
    id: int | None = None

    @property
    def total_usd(self) -> Decimal:
        return r2(sum((l.cantidad * l.precio_usd for l in self.lineas), CERO))

    @property
    def total_cup(self) -> Decimal:
        return r2(sum((l.cantidad * l.precio_cup for l in self.lineas), CERO))


@dataclass
class Devolucion:
    ticket: Ticket
    linea: Linea
    fecha: datetime
    cantidad: Decimal
    reembolso_usd: Decimal
    motivo: str | None
    reingresa: bool
    id: int | None = None


@dataclass
class Compra:
    referencia: str
    fecha: datetime
    proveedor: str
    estado: str
    lineas: list[tuple[str, Decimal, Decimal]]       # (sku, cantidad, coste unitario USD)
    id: int | None = None

    @property
    def total_usd(self) -> Decimal:
        return r2(sum((q * c for _, q, c in self.lineas), CERO))


@dataclass
class Conteo:
    sku: str
    fecha: datetime
    stock: Decimal
    coste_usd: Decimal | None
    donde: str


@dataclass
class Movimiento:
    sku: str
    fecha: datetime
    tipo: str
    cantidad: Decimal
    referencia: object | None = None                 # Ticket, Compra o Devolucion


@dataclass
class Carga:
    ahora: datetime
    productos: dict[str, Producto]
    config_categorias: dict[str, dict]               # solo las que vienen en categorias.csv (se actualizan)
    tickets: list[Ticket]
    devoluciones: list[Devolucion]
    compras: list[Compra]
    movimientos: list[Movimiento]
    precios: dict[str, list[tuple[Decimal, datetime, datetime | None]]]   # sku → [(usd, desde, hasta)]
    inventario: dict[str, tuple[Decimal, Decimal, datetime]]              # sku → (stock, coste medio, actualizado)
    tasas: dict[date, tuple[Decimal, str]]                                # solo las nuevas o corregidas


class Tasas:
    """Tasa USD→CUP de cada día: la del propio día o, si falta, la última anterior."""

    def __init__(self, valores: dict[date, Decimal]):
        self.valores = dict(valores)
        self._dias = sorted(self.valores)

    def poner(self, d: date, v: Decimal) -> None:
        if d not in self.valores:
            bisect.insort(self._dias, d)
        self.valores[d] = v

    def en(self, d: date) -> Decimal | None:
        i = bisect.bisect_right(self._dias, d)
        if i:
            return self.valores[self._dias[i - 1]]
        return self.valores[self._dias[0]] if self._dias else None


# Construcción ----------------------------------------------------------------------------------------------

class Constructor:
    def __init__(self, tablas: list[Tabla], ahora: datetime, tasas_bd: dict[date, Decimal] | None = None,
                 avisos_lectura: list[str] | None = None, tasas_descargadas: dict[date, Decimal] | None = None):
        self.tablas = tablas
        self.ahora = ahora.astimezone(ZONA)
        self.inf = Informe(avisos_archivo=list(avisos_lectura or []))
        self.tasas_bd = dict(tasas_bd or {})
        self.tasas = Tasas(self.tasas_bd)
        self.tasas_nuevas: dict[date, tuple[Decimal, str]] = {}
        for d, v in (tasas_descargadas or {}).items():
            self.tasas.poner(d, v)
            self.tasas_nuevas[d] = (v, "elTOQUE")
        self.productos: dict[str, Producto] = {}
        self.config: dict[str, dict] = {}

    def _de(self, tipo: str) -> list[Tabla]:
        return [t for t in self.tablas if t.tipo == tipo]

    def _fecha(self, f: Fila, clave: str = "fecha", obligatoria: bool = True, hora: object = None) -> tuple[datetime, bool] | None:
        r = L.fecha_hora(f.get(clave), hora, clave.replace("_", " "))
        if r is None:
            if obligatoria:
                raise ErrorDato(f"falta {clave.replace('_', ' ')}")
            return None
        dt, solo = r
        if dt.astimezone(ZONA) > self.ahora + timedelta(minutes=5) and not (solo and dt.date() == self.ahora.date()):
            raise ErrorDato(f"{clave} en el futuro: {dt.astimezone(ZONA):%d/%m/%Y %H:%M}")
        return dt.astimezone(ZONA), solo

    def _positivo(self, f: Fila, clave: str, cero: bool = False) -> Decimal:
        v = L.numero(f.get(clave), clave)
        if v is None:
            raise ErrorDato(f"falta {clave}")
        if v < 0 or (v == 0 and not cero):
            raise ErrorDato(f"{clave} debe ser {'cero o más' if cero else 'mayor que cero'}: {v}")
        return v

    def _usd(self, valor: Decimal, mon: str, d: date, tasa: Decimal | None = None) -> Decimal:
        if mon == "USD":
            return valor
        t = tasa or self.tasas.en(d)
        if not t:
            raise ErrorDato(f"no hay tasa USD→CUP para el {d:%d/%m/%Y} (añade tasas.csv o la columna tasa)")
        return valor / t

    def _producto(self, sku: str, nombre: str | None, donde: str) -> Producto:
        p = self.productos.get(sku)
        if p is None:
            p = Producto(sku, nombre or sku, SIN_CATEGORIA, SIN_CATEGORIA, automatico=True)
            self.productos[sku] = p
            self.inf.aviso("auto", "Productos que no están en el catálogo y se crean en «Sin categoría»", f"{sku} ({donde})")
        return p

    # Archivos de referencia --------------------------------------------------------------------------------

    def categorias(self) -> None:
        for t in self._de("categorias"):
            for f in t.filas:
                try:
                    nombre = L.texto(f.get("categoria"))
                    if not nombre:
                        raise ErrorDato("falta categoria")
                    self.config[nombre] = {
                        "linea": L.opcion(f.get("linea"), L.LINEAS, CONFIG_DEFECTO["linea"], "línea"),
                        "plazo_dias": int(L.numero(f.get("plazo_dias"), "plazo") or CONFIG_DEFECTO["plazo_dias"]),
                        "dias_stock_minimo": int(L.numero(f.get("dias_stock_minimo"), "días de stock mínimo")
                                                 or CONFIG_DEFECTO["dias_stock_minimo"]),
                        "basico": L.booleano(f.get("basico"), False, "básico"),
                    }
                except ErrorDato as e:
                    self.inf.error(f.donde, str(e))

    def tasas_archivo(self) -> None:
        for t in self._de("tasas"):
            for f in t.filas:
                try:
                    dt, _ = self._fecha(f)
                    v = self._positivo(f, "usd_cup")
                    self.tasas.poner(dt.date(), v)
                    if self.tasas_bd.get(dt.date()) != v:
                        self.tasas_nuevas[dt.date()] = (v, "archivo")
                except ErrorDato as e:
                    self.inf.error(f.donde, str(e))

    def catalogo(self) -> list[Conteo]:
        conteos = []
        for t in self._de("productos"):
            for f in t.filas:
                try:
                    sku = L.codigo(f.get("sku"))
                    nombre = L.texto(f.get("nombre"))
                    cat = L.texto(f.get("categoria"))
                    if not sku or not nombre or not cat:
                        raise ErrorDato("faltan sku, nombre o categoría")
                    if sku in self.productos:
                        self.inf.aviso("sku_dup", "SKU repetido en el catálogo (manda la última fila)", sku)
                    mon = L.moneda(f.get("moneda"))
                    precio = next(((v, m) for v, m in ((L.numero(f.get("precio_usd"), "precio"), "USD"),
                                                       (L.numero(f.get("precio_cup"), "precio"), "CUP"),
                                                       (L.numero(f.get("precio"), "precio"), mon)) if v), None)
                    coste = next(((v, m) for v, m in ((L.numero(f.get("coste_usd"), "coste"), "USD"),
                                                      (L.numero(f.get("coste_cup"), "coste"), "CUP"),
                                                      (L.numero(f.get("coste"), "coste"), mon)) if v is not None), None)
                    if precio and precio[0] < 0 or coste and coste[0] < 0:
                        raise ErrorDato("precio y coste no pueden ser negativos")
                    alta = self._fecha(f, "alta", obligatoria=False)
                    p = Producto(sku, nombre, cat, L.texto(f.get("subcategoria")) or cat,
                                 unidad=L.texto(f.get("unidad")) or "unidad",
                                 stock_minimo=L.numero(f.get("stock_minimo"), "stock mínimo") or CERO,
                                 activo=L.booleano(f.get("activo"), True, "activo"),
                                 precio=precio, coste=coste, alta=alta[0] if alta else None)
                    if p.stock_minimo < 0:
                        raise ErrorDato("stock mínimo negativo")
                    self.productos[sku] = p
                    stock = L.numero(f.get("stock"), "stock")
                    if stock is not None:
                        fs = self._fecha(f, "fecha_stock", obligatoria=False)
                        conteos.append(Conteo(sku, self._momento_conteo(fs), stock, None, f.donde))
                except ErrorDato as e:
                    self.inf.error(f.donde, str(e))
        return conteos

    def _momento_conteo(self, fs: tuple[datetime, bool] | None) -> datetime:
        if fs is None:
            return self.ahora
        dt, solo = fs
        if solo:                                     # solo fecha: stock al cierre de ese día
            dt = datetime.combine(dt.date(), time(23, 59, 59), ZONA)
        return min(dt, self.ahora)

    # Movimientos del negocio -------------------------------------------------------------------------------

    def ventas(self) -> list[Ticket]:
        tickets: dict[str, Ticket] = {}
        origen: dict[str, str] = {}
        for t in self._de("ventas"):
            grupos: dict[str, list[Fila]] = defaultdict(list)
            for f in t.filas:
                num = L.codigo(f.get("numero")) or f"{L.normalizar(t.archivo)}-{f.fila}".upper()
                grupos[num].append(f)
            for num, filas in grupos.items():
                try:
                    ticket = self._ticket(num, filas)
                except ErrorDato as e:
                    self.inf.error(e.args[1] if len(e.args) > 1 else filas[0].donde, f"ticket {num}: {e.args[0]}")
                    continue
                if num in tickets:
                    self.inf.aviso("ticket_rep", "Tickets que aparecen en más de un archivo (manda el último)",
                                   f"{num} ({origen[num]} → {t.archivo})")
                tickets[num] = ticket
                origen[num] = t.archivo
        return sorted(tickets.values(), key=lambda x: (x.fecha, x.numero))

    def _ticket(self, num: str, filas: list[Fila]) -> Ticket:
        f0 = filas[0]
        try:
            fecha, solo = self._fecha(f0, hora=f0.get("hora"))
            if solo:
                fecha = min(fecha.replace(hour=12), self.ahora)
                self.inf.aviso("sin_hora", "Ventas sin hora (se sitúan a las 12:00)", f0.donde)
            canal = L.opcion(f0.get("canal"), L.CANALES, "tienda_fisica", "canal")
            estado = L.opcion(f0.get("estado"), L.ESTADOS_VENTA, "completada", "estado")
            tasa = next((L.numero(f.get("tasa"), "tasa") for f in filas if f.get("tasa") is not None), None)
            if tasa is not None and tasa <= 0:
                raise ErrorDato("la tasa debe ser mayor que cero")
            tasa_dada = tasa is not None
            tasa = tasa or self.tasas.en(fecha.date())
            anulada_en = None
            if estado == "anulada":
                a = self._fecha(f0, "anulada_en", obligatoria=False)
                anulada_en = max(a[0], fecha) if a else fecha
        except ErrorDato as e:
            raise ErrorDato(str(e), f0.donde) from None
        lineas, pagos = [], defaultdict(lambda: CERO)
        for f in filas:
            try:
                sku = L.codigo(f.get("sku"))
                if not sku:
                    raise ErrorDato("falta sku")
                if f is not f0 and f.get("fecha") is not None and f.get("fecha") != f0.get("fecha"):
                    self.inf.aviso("fecha_linea", "Líneas de un mismo ticket con fecha distinta (manda la primera)", f.donde)
                q = self._positivo(f, "cantidad")
                mon = L.moneda(f.get("moneda"))
                precio = L.numero(f.get("precio"), "precio")
                if precio is None:
                    importe = L.numero(f.get("importe"), "importe")
                    if importe is None:
                        raise ErrorDato("falta precio o importe")
                    precio = importe / q
                if precio < 0:
                    raise ErrorDato("precio negativo")
                if not tasa:
                    raise ErrorDato(f"no hay tasa USD→CUP para el {fecha:%d/%m/%Y} (añade tasas.csv o la columna tasa)")
                if mon == "USD":
                    usd, cup = r2(precio), r2(precio * tasa)
                else:
                    usd, cup = r2(precio / tasa), r2(precio)
                metodo = L.opcion(f.get("metodo_pago") or f0.get("metodo_pago"), L.METODOS, "efectivo", "método de pago")
                if metodo == "transferencia" and mon == "USD":
                    raise ErrorDato("una transferencia se registra en CUP (el esquema no admite transferencias en USD)")
                coste = L.numero(f.get("coste_unitario_usd"), "coste")
                if coste is not None and coste < 0:
                    raise ErrorDato("coste negativo")
                self._producto(sku, L.texto(f.get("nombre")), f.donde)
                lineas.append(Linea(sku, q, usd, cup, coste))
                pagos[(mon, metodo)] += precio * q
            except ErrorDato as e:
                raise ErrorDato(str(e), f.donde) from None
        if tasa_dada and fecha.date() not in self.tasas.valores:
            self.tasas_nuevas.setdefault(fecha.date(), (tasa, "ventas"))
        return Ticket(num, fecha, canal, estado, tasa, lineas, {k: r2(v) for k, v in pagos.items() if v > 0},
                      anulada_en, L.texto(f0.get("motivo_anulacion")) if estado == "anulada" else None)

    def compras(self) -> list[Compra]:
        compras: dict[str, Compra] = {}
        for t in self._de("compras"):
            grupos: dict[str, list[Fila]] = defaultdict(list)
            for f in t.filas:
                ref = L.codigo(f.get("referencia")) or f"{L.normalizar(t.archivo)}-{f.fila}".upper()
                grupos[ref].append(f)
            for ref, filas in grupos.items():
                f0, f = filas[0], filas[0]
                try:
                    fecha, solo = self._fecha(f0)
                    if solo:
                        fecha = min(fecha.replace(hour=8), self.ahora)
                    estado = L.opcion(f0.get("estado"), L.ESTADOS_COMPRA, "recibida", "estado")
                    proveedor = L.texto(f0.get("proveedor"))
                    if not proveedor:
                        proveedor = SIN_PROVEEDOR
                        self.inf.aviso("sin_prov", "Compras sin proveedor (se agrupan en «Sin proveedor»)", f0.donde)
                    lineas = []
                    for f in filas:
                        sku = L.codigo(f.get("sku"))
                        if not sku:
                            raise ErrorDato("falta sku")
                        q = self._positivo(f, "cantidad")
                        coste = self._positivo(f, "coste_unitario", cero=True)
                        usd = r2(self._usd(coste, L.moneda(f.get("moneda")), fecha.date()))
                        self._producto(sku, L.texto(f.get("nombre")), f.donde)
                        lineas.append((sku, q, usd))
                except ErrorDato as e:
                    self.inf.error(f.donde, f"compra {ref}: {e}")
                    continue
                compras[ref] = Compra(ref, fecha, proveedor, estado, lineas)
        return sorted(compras.values(), key=lambda c: (c.fecha, c.referencia))

    def devoluciones(self, tickets: list[Ticket]) -> list[Devolucion]:
        por_numero = {t.numero: t for t in tickets}
        salida = []
        for t in self._de("devoluciones"):
            for f in t.filas:
                try:
                    num, sku = L.codigo(f.get("numero")), L.codigo(f.get("sku"))
                    ticket = por_numero.get(num or "")
                    if ticket is None:
                        raise ErrorDato(f"no existe el ticket {num}")
                    if ticket.estado != "completada":
                        raise ErrorDato(f"el ticket {num} está anulado")
                    fecha, solo = self._fecha(f)
                    if solo:
                        fecha = min(fecha.replace(hour=12), self.ahora)
                    fecha = max(fecha, ticket.fecha)
                    q = self._positivo(f, "cantidad")
                    linea = next((l for l in ticket.lineas if l.sku == sku and l.cantidad - l.devuelta >= q), None)
                    if linea is None:
                        raise ErrorDato(f"el ticket {num} no tiene {q} uds. de {sku} por devolver")
                    reembolso = L.numero(f.get("reembolso"), "reembolso")
                    if reembolso is None:
                        usd = r2(q * linea.precio_usd)
                    else:
                        usd = r2(self._usd(reembolso, L.moneda(f.get("moneda")), fecha.date(), ticket.tasa))
                    linea.devuelta += q
                    salida.append(Devolucion(ticket, linea, fecha, q, usd, L.texto(f.get("motivo")),
                                             L.booleano(f.get("reingresa_stock"), True, "reingresa al stock")))
                except ErrorDato as e:
                    self.inf.error(f.donde, str(e))
        return salida

    def conteos(self) -> list[Conteo]:
        salida = []
        for t in self._de("inventario"):
            for f in t.filas:
                try:
                    sku = L.codigo(f.get("sku"))
                    if not sku:
                        raise ErrorDato("falta sku")
                    stock = L.numero(f.get("stock"), "stock")
                    if stock is None or stock < 0:
                        raise ErrorDato("stock vacío o negativo")
                    coste = L.numero(f.get("coste_medio_usd"), "coste")
                    self._producto(sku, None, f.donde)
                    salida.append(Conteo(sku, self._momento_conteo(self._fecha(f, obligatoria=False)), stock, coste, f.donde))
                except ErrorDato as e:
                    self.inf.error(f.donde, str(e))
        return salida

    def precios_hist(self) -> dict[str, list[tuple[datetime, Decimal, str]]]:
        salida: dict[str, list] = defaultdict(list)
        for t in self._de("precios"):
            for f in t.filas:
                try:
                    sku = L.codigo(f.get("sku"))
                    if sku not in self.productos:
                        raise ErrorDato(f"el producto {sku} no está en el catálogo")
                    desde, _ = self._fecha(f, "desde")
                    v, m = next(((v, m) for v, m in ((L.numero(f.get("precio_usd"), "precio"), "USD"),
                                                     (L.numero(f.get("precio_cup"), "precio"), "CUP"),
                                                     (L.numero(f.get("precio"), "precio"), L.moneda(f.get("moneda"))))
                                 if v is not None), (None, None))
                    if not v or v <= 0:
                        raise ErrorDato("falta el precio o no es mayor que cero")
                    salida[sku].append((desde, v, m))
                except ErrorDato as e:
                    self.inf.error(f.donde, str(e))
        return salida

    # Inventario --------------------------------------------------------------------------------------------

    def inventario(self, tickets, compras, devoluciones, conteos):
        eventos: dict[str, list] = defaultdict(list)     # sku → [(fecha, orden, tipo, cantidad, ref, coste)]
        for c in compras:
            if c.estado == "recibida":
                for sku, q, coste in c.lineas:
                    eventos[sku].append((c.fecha, 0, "compra", q, c, coste))
        for t in tickets:
            for l in t.lineas:
                eventos[l.sku].append((t.fecha, 1, "venta", -l.cantidad, t, l))
                if t.estado == "anulada":
                    eventos[l.sku].append((t.anulada_en, 2, "anulacion_venta", l.cantidad, t, l))
        for d in devoluciones:
            if d.reingresa:
                eventos[d.linea.sku].append((d.fecha, 3, "devolucion", d.cantidad, d, d.linea))
        ultimo: dict[tuple[str, datetime], Conteo] = {}
        for c in conteos:
            ultimo[(c.sku, c.fecha)] = c                  # el mismo producto y momento: manda el último archivo
        for c in ultimo.values():
            eventos[c.sku].append((c.fecha, 9, "conteo", c.stock, c, c.coste_usd))

        movimientos: list[Movimiento] = []
        inventario: dict[str, tuple[Decimal, Decimal, datetime]] = {}
        for sku, p in self.productos.items():
            ev = sorted(eventos.get(sku, []), key=lambda e: (e[0], e[1]))
            coste = self._coste_inicial(p, ev)
            # Saldo inicial: lo necesario para que el stock nunca sea negativo antes del primer conteo y, si hay
            # conteo, para llegar a él sin ajustes.
            i_conteo = next((i for i, e in enumerate(ev) if e[2] == "conteo"), None)
            previos = ev[:i_conteo] if i_conteo is not None else ev
            acumulado, minimo = CERO, CERO
            for e in previos:
                acumulado += e[3]
                minimo = min(minimo, acumulado)
            saldo = -minimo
            if i_conteo is not None:
                saldo = max(saldo, ev[i_conteo][3] - acumulado)
            elif ev:
                self.inf.aviso("sin_conteo", "Productos con movimientos y sin conteo de inventario (stock deducido de compras y ventas)", sku)
            stock = CERO
            if saldo > 0 and previos:
                inicio = previos[0][0] - timedelta(minutes=1)
                movimientos.append(Movimiento(sku, inicio, "ajuste_positivo", saldo))
                stock = saldo
            for fecha, _, tipo, q, ref, extra in ev:
                if tipo == "conteo":
                    if extra is not None:
                        coste = extra
                    if q != stock:
                        movimientos.append(Movimiento(sku, fecha, "ajuste_positivo" if q > stock else "ajuste_negativo", q - stock))
                        if previos or ref is not ev[i_conteo][4]:     # un primer conteo sin movimientos previos es el saldo inicial
                            self.inf.aviso("dif_conteo", "Conteos que no cuadran con las ventas y compras (se ajusta el stock)",
                                           f"{sku} {fecha:%d/%m} {stock:g}→{q:g}")
                    stock = q
                    continue
                if tipo == "compra":
                    coste = self._media(stock, coste, q, extra)
                elif tipo == "venta":
                    if extra.coste_usd is None:
                        extra.coste_usd = r4(coste)
                        if coste == 0:
                            self.inf.aviso("sin_coste", "Productos vendidos sin coste conocido (margen sobreestimado)", sku)
                    if stock + q < 0:
                        falta = -(stock + q)
                        movimientos.append(Movimiento(sku, fecha - timedelta(seconds=1), "ajuste_positivo", falta))
                        stock += falta
                        self.inf.aviso("negativo", "Ventas sin stock suficiente tras un conteo (se añade un ajuste)",
                                       f"{sku} {fecha:%d/%m}")
                elif tipo in ("anulacion_venta", "devolucion"):
                    coste = self._media(stock, coste, q, extra.coste_usd or coste)
                stock += q
                movimientos.append(Movimiento(sku, fecha, tipo, q, ref))
            inventario[sku] = (stock, r4(coste), ev[-1][0] if ev else self.ahora)
        return movimientos, inventario

    @staticmethod
    def _media(stock: Decimal, coste: Decimal, q: Decimal, coste_q: Decimal) -> Decimal:
        if stock + q <= 0:
            return coste_q
        return (max(stock, CERO) * coste + q * coste_q) / (max(stock, CERO) + q)

    def _coste_inicial(self, p: Producto, ev: list) -> Decimal:
        if p.coste:
            v, m = p.coste
            try:
                return self._usd(v, m, (p.alta or self.ahora).date())
            except ErrorDato:
                pass
        for e in ev:
            if e[2] == "compra":
                return e[5]
            if e[2] == "venta" and e[5].coste_usd is not None:
                return e[5].coste_usd
            if e[2] == "conteo" and e[5] is not None:
                return e[5]
        return CERO

    # Precios -----------------------------------------------------------------------------------------------

    def precios(self, historial, tickets) -> dict[str, list[tuple[Decimal, datetime, datetime | None]]]:
        ultima_venta: dict[str, tuple[datetime, Decimal]] = {}
        for t in tickets:
            if t.estado == "completada":
                for l in t.lineas:
                    if l.precio_usd > 0:
                        ultima_venta[l.sku] = (t.fecha, l.precio_usd)
        salida = {}
        for sku, p in self.productos.items():
            puntos: list[tuple[datetime, Decimal]] = []
            for desde, v, m in sorted(historial.get(sku, []), key=lambda x: x[0]):
                try:
                    puntos.append((desde, r2(self._usd(v, m, desde.date()))))
                except ErrorDato as e:
                    self.inf.error(f"precios de {sku}", str(e))
            actual = None
            if p.precio:
                try:
                    actual = r2(self._usd(p.precio[0], p.precio[1], self.ahora.date()))
                except ErrorDato as e:
                    self.inf.error(f"catálogo, {sku}", str(e))
            elif not puntos and sku in ultima_venta:
                actual = ultima_venta[sku][1]
                if p.activo:
                    self.inf.aviso("precio_venta", "Productos sin precio en el catálogo (se usa el de su última venta)", sku)
            if actual and actual > 0:
                if not puntos:
                    puntos.append((p.alta, actual))
                elif puntos[-1][1] != actual:
                    puntos.append((max(self.ahora - timedelta(seconds=1), puntos[-1][0] + timedelta(seconds=1)), actual))
            limpio: list[tuple[datetime, Decimal]] = []
            for desde, v in puntos:
                if limpio and limpio[-1][1] == v:
                    continue
                if limpio and limpio[-1][0] == desde:
                    limpio[-1] = (desde, v)
                else:
                    limpio.append((desde, v))
            salida[sku] = [(v, desde, limpio[i + 1][0] if i + 1 < len(limpio) else None) for i, (desde, v) in enumerate(limpio)]
        return salida

    # Todo ----------------------------------------------------------------------------------------------------

    def construir(self) -> tuple[Carga, Informe]:
        self.categorias()
        self.tasas_archivo()
        conteos = self.catalogo()
        tickets = self.ventas()
        compras = self.compras()
        devoluciones = self.devoluciones(tickets)
        conteos += self.conteos()
        historial = self.precios_hist()
        movimientos, inventario = self.inventario(tickets, compras, devoluciones, conteos)
        # Fecha de alta: la indicada o el primer movimiento, lo que sea antes.
        primero: dict[str, datetime] = {}
        for m in movimientos:
            if m.sku not in primero or m.fecha < primero[m.sku]:
                primero[m.sku] = m.fecha
        for sku, p in self.productos.items():
            candidatos = [x for x in (p.alta, primero.get(sku)) if x is not None]
            p.alta = min(candidatos) if candidatos else self.ahora
        precios = self.precios(historial, tickets)

        nuevos = [p for p in self.productos.values() if p.automatico]
        self.inf.resumen = {
            "productos": f"{len(self.productos)} ({sum(p.activo for p in self.productos.values())} activos"
                         + (f", {len(nuevos)} creados desde ventas o compras" if nuevos else "") + ")",
            "ventas": f"{len(tickets)} tickets ({sum(t.estado == 'anulada' for t in tickets)} anulados), "
                      f"{sum(len(t.lineas) for t in tickets)} líneas",
            "periodo": (f"{tickets[0].fecha:%d/%m/%Y} – {tickets[-1].fecha:%d/%m/%Y %H:%M}" if tickets else "sin ventas"),
            "importe": f"{sum(t.total_usd for t in tickets if t.estado == 'completada'):,.2f} USD".replace(",", " "),
            "devoluciones": len(devoluciones),
            "compras": f"{len(compras)} ({sum(c.estado == 'pendiente' for c in compras)} pendientes)",
            "conteos de inventario": len(conteos),
            "tasas nuevas o corregidas": len(self.tasas_nuevas),
        }
        carga = Carga(self.ahora, self.productos, self.config, tickets, devoluciones, compras, movimientos, precios,
                      inventario, self.tasas_nuevas)
        return carga, self.inf
