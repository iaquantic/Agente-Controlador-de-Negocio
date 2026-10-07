"""Importador: lectura de archivos y construcción de la carga (sin base de datos)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from agente_interno.importador import preparar
from agente_interno.importador import lectura as L
from agente_interno.importador.lectura import ZONA

EJEMPLO = Path(__file__).resolve().parents[1] / "agente_interno" / "importador" / "plantillas" / "ejemplo"
AHORA = datetime(2026, 10, 5, 9, 0, tzinfo=ZONA)
D = Decimal


def carpeta(tmp_path: Path, **archivos: str) -> Path:
    for nombre, contenido in archivos.items():
        (tmp_path / f"{nombre}.csv").write_text(contenido.strip() + "\n", encoding="utf-8")
    return tmp_path


CATALOGO = """sku;nombre;categoria;precio;coste
A1;Arroz 1 kg;Alimentos;1,20;0,80
B2;Aceite 1 L;Alimentos;3,50;2,50
"""
TASAS = "fecha,usd_cup\n2026-09-01,700\n2026-10-01,750"


# Lectura ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("1,20", "1.20"), ("1.20", "1.20"), ("1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("1.250", "1250"),
    ("0,250", "0.250"), ("12.345.678", "12345678"), ("$ 7,50", "7.50"), ("10220 CUP", "10220"), ("-3", "-3"), (5, "5"),
])
def test_numeros(texto, esperado):
    assert L.numero(texto) == D(esperado)


def test_numero_no_valido():
    with pytest.raises(L.ErrorDato):
        L.numero("doce")


@pytest.mark.parametrize("texto,esperado,solo", [
    ("04/10/2026", datetime(2026, 10, 4), True),
    ("4/10/26 14:30", datetime(2026, 10, 4, 14, 30), False),
    ("2026-10-04 09:05:07", datetime(2026, 10, 4, 9, 5, 7), False),
    ("2026-10-04", datetime(2026, 10, 4), True),
    ("04-10-2026 2:15 pm", datetime(2026, 10, 4, 14, 15), False),
])
def test_fechas_en_hora_de_la_habana(texto, esperado, solo):
    dt, s = L.fecha_hora(texto)
    assert dt == esperado.replace(tzinfo=ZONA) and s is solo


def test_fecha_con_hora_aparte_y_con_zona():
    assert L.fecha_hora("04/10/2026", "15:40")[0] == datetime(2026, 10, 4, 15, 40, tzinfo=ZONA)
    dt, _ = L.fecha_hora("2026-10-04T12:00:00Z")
    assert dt.astimezone(ZONA).hour == 8


def test_tipo_de_archivo_por_su_nombre():
    assert L.tipo_de("ventas_2026-10.csv") == "ventas"
    assert L.tipo_de("Productos.xlsx") == "productos"
    assert L.tipo_de("inventario 04-10.csv") == "inventario"
    assert L.tipo_de("informe.csv") is None


def test_columnas_por_sinonimos_y_mapeo(tmp_path):
    (tmp_path / "productos.csv").write_text("Código;Descripción;Familia;PVP\nX1;Uno;Varios;2\n", encoding="utf-8")
    (tmp_path / "ventas.csv").write_text("Nro Doc;Fecha;Código;Cant\nV1;01/10/2026 10:00;X1;1\n", encoding="utf-8")
    (tmp_path / "mapeo.json").write_text('{"ventas": {"Nro Doc": "numero"}}', encoding="utf-8")
    tablas, avisos = L.leer_carpeta(tmp_path)
    prod = next(t for t in tablas if t.tipo == "productos").filas[0]
    venta = next(t for t in tablas if t.tipo == "ventas").filas[0]
    assert prod.get("sku") == "X1" and prod.get("categoria") == "Varios" and prod.get("precio") == "2"
    assert venta.get("numero") == "V1" and venta.get("cantidad") == "1"
    assert not avisos


def test_excel_con_varias_hojas(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    libro = openpyxl.Workbook()
    h = libro.active
    h.title = "Productos"
    h.append(["SKU", "Nombre", "Categoría", "Precio USD"])
    h.append(["A1", "Arroz", "Alimentos", 1.2])
    v = libro.create_sheet("Ventas")
    v.append(["Ticket", "Fecha", "SKU", "Cantidad", "Precio"])
    v.append([1001, datetime(2026, 10, 1, 10, 30), "a1", 2, 1.2])
    libro.save(tmp_path / "datos.xlsx")
    (tmp_path / "tasas.csv").write_text(TASAS, encoding="utf-8")
    carga, inf = preparar(tmp_path, AHORA)
    assert not inf.errores
    t = carga.tickets[0]
    assert t.numero == "1001" and t.fecha == datetime(2026, 10, 1, 10, 30, tzinfo=ZONA)
    assert t.lineas[0].sku == "A1" and t.total_usd == D("2.40") and t.total_cup == D("1800.00")


# Construcción -------------------------------------------------------------------------------------------------

def test_ejemplo_de_las_plantillas_sin_errores():
    carga, inf = preparar(EJEMPLO, AHORA)
    assert inf.errores == []
    assert len(carga.productos) == 8 and len(carga.tickets) == 16
    # Café: precio de catálogo en CUP convertido con la tasa de hoy (752 desde el 3/10).
    assert carga.precios["CAF-250"][-1][0] == D("2.53")
    # Pollo: historial de precios del archivo.
    assert [p[0] for p in carga.precios["POL-10LB"]] == [D("13.50"), D("14.00")]
    # Venta en CUP: precio en USD con la tasa del día (728 el 20/9).
    pollo = next(t for t in carga.tickets if t.numero == "T-1002")
    assert pollo.lineas[0].precio_usd == D("14.04") and pollo.pagos == {("CUP", "transferencia"): D("10220.00")}


def test_stock_se_reconstruye_desde_el_conteo(tmp_path):
    c = carpeta(tmp_path, productos=CATALOGO, tasas=TASAS,
                ventas="numero,fecha,sku,cantidad,precio\nV1,2026-09-10 10:00,A1,5,1.2\nV2,2026-09-20 10:00,A1,3,1.2",
                inventario="sku,stock,fecha\nA1,12,2026-09-30")
    carga, inf = preparar(c, AHORA)
    movs = [(m.tipo, m.cantidad) for m in carga.movimientos if m.sku == "A1"]
    # Saldo inicial = 12 + 5 + 3: el conteo cuadra sin ajustes.
    assert movs == [("ajuste_positivo", D(20)), ("venta", D(-5)), ("venta", D(-3))]
    assert carga.inventario["A1"][0] == D(12)
    assert not any("Conteos que no cuadran" in a for a in inf.avisos)


def test_conteo_posterior_genera_ajuste_y_aviso(tmp_path):
    c = carpeta(tmp_path, productos=CATALOGO, tasas=TASAS,
                compras="referencia,fecha,proveedor,sku,cantidad,coste_unitario\nC1,2026-09-01,P,A1,10,0.80",
                ventas="numero,fecha,sku,cantidad,precio\nV1,2026-09-10 10:00,A1,4,1.2",
                inventario="sku,stock,fecha\nA1,5,2026-09-30")
    carga, inf = preparar(c, AHORA)
    movs = [(m.tipo, m.cantidad) for m in carga.movimientos if m.sku == "A1"]
    assert movs == [("compra", D(10)), ("venta", D(-4)), ("ajuste_negativo", D(-1))]
    assert any("A1 30/09 6→5" in a for a in inf.avisos)


def test_ventas_sin_stock_tras_un_conteo(tmp_path):
    c = carpeta(tmp_path, productos=CATALOGO, tasas=TASAS,
                inventario="sku,stock,fecha\nA1,2,2026-09-01",
                ventas="numero,fecha,sku,cantidad,precio\nV1,2026-09-10 10:00,A1,5,1.2")
    carga, inf = preparar(c, AHORA)
    assert carga.inventario["A1"][0] == 0
    assert all(m.cantidad > 0 or m.tipo in ("venta", "ajuste_negativo") for m in carga.movimientos)
    assert any("sin stock suficiente" in a for a in inf.avisos)


def test_coste_medio_ponderado_y_coste_de_cada_venta(tmp_path):
    c = carpeta(tmp_path, productos="sku,nombre,categoria,precio\nA1,Arroz,Alimentos,2", tasas=TASAS,
                compras="referencia,fecha,proveedor,sku,cantidad,coste_unitario\n"
                        "C1,2026-09-01,P,A1,10,1.00\nC2,2026-09-15,P,A1,10,2.00",
                ventas="numero,fecha,sku,cantidad,precio\nV1,2026-09-10 10:00,A1,5,2\nV2,2026-09-20 10:00,A1,5,2")
    carga, _ = preparar(c, AHORA)
    v1, v2 = carga.tickets
    assert v1.lineas[0].coste_usd == D("1.0000")
    assert v2.lineas[0].coste_usd == D("1.6667")              # (5 × 1 + 10 × 2) / 15
    assert carga.inventario["A1"][:2] == (D(10), D("1.6667"))


def test_anulada_y_devolucion_mueven_el_stock(tmp_path):
    c = carpeta(tmp_path, productos=CATALOGO, tasas=TASAS,
                inventario="sku,stock,fecha\nA1,10,2026-09-01 08:00",
                ventas="numero,fecha,sku,cantidad,precio,estado\nV1,2026-09-10 10:00,A1,2,1.2,anulada\n"
                       "V2,2026-09-11 10:00,A1,3,1.2,completada",
                devoluciones="numero,sku,fecha,cantidad\nV2,A1,2026-09-12,1")
    carga, inf = preparar(c, AHORA)
    assert not inf.errores
    tipos = [(m.tipo, m.cantidad) for m in carga.movimientos if m.sku == "A1"]
    assert ("anulacion_venta", D(2)) in tipos and ("devolucion", D(1)) in tipos
    assert carga.inventario["A1"][0] == D(8)
    d = carga.devoluciones[0]
    assert d.reembolso_usd == D("1.20") and d.fecha.hour == 12
    v1 = carga.tickets[0]
    assert v1.estado == "anulada" and v1.anulada_en == v1.fecha


def test_errores_claros_por_fila(tmp_path):
    c = carpeta(tmp_path, productos=CATALOGO, tasas=TASAS, ventas="""
numero,fecha,sku,cantidad,precio,moneda,metodo_pago
V1,2026-09-10 10:00,A1,0,1.2,USD,efectivo
V2,2027-01-01 10:00,A1,1,1.2,USD,efectivo
V3,2026-09-10 10:00,A1,1,1.2,USD,transferencia
V4,2026-09-10 10:00,A1,1,,USD,efectivo
V5,2026-09-10 10:00,A1,1,1.2,USD,efectivo
""", devoluciones="numero,sku,fecha,cantidad\nV5,A1,2026-09-11,2\nV9,A1,2026-09-11,1")
    carga, inf = preparar(c, AHORA)
    mensajes = " | ".join(f"{d}: {m}" for d, m in inf.errores)
    assert "ventas.csv, fila 2: ticket V1: cantidad debe ser mayor que cero" in mensajes
    assert "en el futuro" in mensajes
    assert "transferencia se registra en CUP" in mensajes
    assert "falta precio o importe" in mensajes
    assert "no tiene 2 uds. de A1 por devolver" in mensajes and "no existe el ticket V9" in mensajes
    assert [t.numero for t in carga.tickets] == ["V5"]


def test_sin_tasa_no_se_puede_convertir_cup(tmp_path):
    c = carpeta(tmp_path, productos=CATALOGO, ventas="numero,fecha,sku,cantidad,precio,moneda\nV1,2026-09-10 10:00,A1,1,800,CUP")
    _, inf = preparar(c, AHORA)
    assert "no hay tasa USD→CUP" in inf.errores[0][1]


def test_tasa_en_la_venta_alimenta_la_tabla_de_tasas(tmp_path):
    c = carpeta(tmp_path, productos=CATALOGO,
                ventas="numero,fecha,sku,cantidad,precio,moneda,tasa\nV1,2026-09-10 10:00,A1,1,840,CUP,700")
    carga, inf = preparar(c, AHORA)
    assert not inf.errores
    assert carga.tickets[0].lineas[0].precio_usd == D("1.20")
    assert carga.tasas == {date(2026, 9, 10): (D(700), "ventas")}


def test_productos_desconocidos_se_crean_y_el_ultimo_archivo_manda(tmp_path):
    c = carpeta(tmp_path, productos=CATALOGO, tasas=TASAS)
    (c / "ventas_1.csv").write_text("numero,fecha,sku,nombre,cantidad,precio\nV1,2026-09-10 10:00,Z9,Zapatos,1,20\n")
    (c / "ventas_2.csv").write_text("numero,fecha,sku,cantidad,precio\nV1,2026-09-10 10:00,A1,2,1.2\n")
    (c / "ventas_3.csv").write_text("numero,fecha,sku,nombre,cantidad,precio\nV2,2026-09-11 10:00,Z9,Zapatos,1,20\n")
    carga, inf = preparar(c, AHORA)
    assert [(t.numero, t.lineas[0].sku) for t in carga.tickets] == [("V1", "A1"), ("V2", "Z9")]
    z = carga.productos["Z9"]
    assert z.automatico and z.nombre == "Zapatos" and z.categoria == "Sin categoría"
    assert carga.precios["Z9"][-1][0] == D("20.00")          # precio de su última venta
    avisos = " ".join(inf.avisos)
    assert "Tickets que aparecen en más de un archivo" in avisos and "Productos que no están en el catálogo" in avisos


def test_lineas_sin_numero_de_ticket_y_sin_hora(tmp_path):
    c = carpeta(tmp_path, productos=CATALOGO, tasas=TASAS,
                ventas="fecha,sku,cantidad,importe\n10/09/2026,A1,2,2.40\n10/09/2026,B2,1,3.50")
    carga, inf = preparar(c, AHORA)
    assert len(carga.tickets) == 2 and all(t.fecha.hour == 12 for t in carga.tickets)
    assert carga.tickets[0].lineas[0].precio_usd == D("1.20")
    assert any("Ventas sin hora" in a for a in inf.avisos)


def test_producto_retirado_y_stock_del_catalogo(tmp_path):
    c = carpeta(tmp_path, tasas=TASAS, productos="sku,nombre,categoria,subcategoria,precio,activo,stock\n"
                                                 "A1,Arroz,Alimentos,Granos,1.2,sí,7\nB2,Vino,Bebidas,,5,no,")
    carga, inf = preparar(c, AHORA)
    assert not any("Conteos que no cuadran" in a for a in inf.avisos)
    a, b = carga.productos["A1"], carga.productos["B2"]
    assert (a.categoria, a.subcategoria, a.activo) == ("Alimentos", "Granos", True)
    assert (b.subcategoria, b.activo) == ("Bebidas", False)
    assert carga.inventario["A1"][0] == D(7) and carga.inventario["B2"][0] == 0


def test_separador_de_la_cabecera_con_decimales_en_coma(tmp_path):
    (tmp_path / "productos.csv").write_text("sku;nombre;categoria;precio\nA1;Arroz;Alimentos;1,20\nB2;Aceite;Alimentos;3,50\n",
                                            encoding="cp1252")
    tablas, _ = L.leer_carpeta(tmp_path)
    assert [f.get("precio") for f in tablas[0].filas] == ["1,20", "3,50"]


def test_carpeta_inexistente(tmp_path):
    with pytest.raises(ValueError, match="No existe la carpeta"):
        preparar(tmp_path / "no", AHORA)


def test_tasas_que_faltan_se_descargan_de_eltoque(tmp_path, monkeypatch):
    from agente_interno.importador import tasas

    pedidas = []

    def descargar(dias, clave):
        pedidas.extend(dias)
        return {d: D(740) for d in dias}

    monkeypatch.setenv("ELTOQUE_API_KEY", "prueba")
    monkeypatch.setattr(tasas, "descargar", descargar)
    c = carpeta(tmp_path, productos=CATALOGO, ventas="numero,fecha,sku,cantidad,precio,moneda\nV1,2026-10-03 10:00,A1,1,888,CUP")
    carga, inf = preparar(c, AHORA, eltoque=True)
    assert not inf.errores
    assert pedidas == [date(2026, 10, 3), date(2026, 10, 4), date(2026, 10, 5)]
    assert carga.tickets[0].lineas[0].precio_usd == D("1.20") and carga.tasas[date(2026, 10, 5)] == (D(740), "elTOQUE")
