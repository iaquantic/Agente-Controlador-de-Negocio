"""Bloque A: herramientas contra la base de datos (10_casos_de_prueba.md).

Las cifras se comparan con un cálculo independiente hecho directamente sobre las tablas,
para que las pruebas valgan con cualquier conjunto de datos generado.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

AGO = {"from": "2026-08-01", "to": "2026-08-31"}
INI, FIN = "2026-08-01 00:00-04", "2026-09-01 00:00-04"


def skus(items):
    return {i["sku"] for i in items}


@pytest.fixture(scope="module")
def agosto(sql):
    """Totales de agosto calculados a mano según 05_reglas_de_negocio.md §5.3."""
    bruto, bruto_cup, tickets = sql(
        "select sum(total_usd), sum(total_cup), count(*) from ventas where estado='completada' and fecha >= %s and fecha < %s",
        (INI, FIN))[0]
    devol, devol_cup, coste_reing = sql(
        "select coalesce(sum(d.reembolso_usd),0), coalesce(sum(d.cantidad*lv.precio_unitario_cup),0),"
        " coalesce(sum(d.cantidad*lv.coste_unitario_usd) filter (where d.reingresa_stock),0)"
        " from devoluciones d join lineas_venta lv on lv.id=d.linea_venta_id where d.fecha >= %s and d.fecha < %s", (INI, FIN))[0]
    coste = sql("select sum(lv.cantidad*lv.coste_unitario_usd) from lineas_venta lv join ventas v on v.id=lv.venta_id"
                " where v.estado='completada' and v.fecha >= %s and v.fecha < %s", (INI, FIN))[0][0] - coste_reing
    anuladas = sql("select count(*) from ventas where estado='anulada' and fecha >= %s and fecha < %s", (INI, FIN))[0][0]
    neto = bruto - devol
    return dict(bruto=bruto, neto=neto, neto_cup=bruto_cup - devol_cup, tickets=tickets, coste=coste,
                margen=round((neto - coste) / neto * 100, 1), anuladas=anuladas, ticket=round(bruto / tickets, 2))


def test_sobre_comun(tool):
    r = tool("get_sales_summary", AGO)
    for campo in ("status", "tool", "params", "period", "data_as_of", "generated_at", "fx", "data", "kinds", "warnings"):
        assert campo in r
    assert r["period"]["timezone"] == "America/Havana"
    assert r["generated_at"] == "2026-09-30T11:30:00-04:00"
    assert "net_usd" in r["kinds"]["calculation"] and "tickets" in r["kinds"]["fact"]


def test_a01_totales_agosto(tool, agosto):
    t = tool("get_sales_summary", AGO)["data"]["totals"]
    assert Decimal(str(t["net_usd"])) == round(agosto["neto"], 2)
    assert Decimal(str(t["net_cup"])) == round(agosto["neto_cup"], 0)
    assert t["tickets"] == agosto["tickets"]
    assert Decimal(str(t["avg_ticket_usd"])) == agosto["ticket"]
    assert Decimal(str(t["cogs_usd"])) == round(agosto["coste"], 2)
    assert Decimal(str(t["gross_margin_pct"])) == agosto["margen"]
    assert t["voided_tickets"] == agosto["anuladas"]


def test_a02_suma_por_dia(tool):
    d = tool("get_sales_summary", {**AGO, "group_by": "day"})["data"]
    assert len(d["groups"]) == 31
    assert round(sum(g["net_usd"] for g in d["groups"]), 2) == pytest.approx(d["totals"]["net_usd"], abs=0.01)
    assert sum(g["tickets"] for g in d["groups"]) == d["totals"]["tickets"]


def test_a03_formas_de_pago(tool, agosto):
    g = tool("get_sales_summary", {**AGO, "group_by": "payment_method"})["data"]["groups"]
    assert {(x["method"], x["currency"]) for x in g} <= {("efectivo", "USD"), ("efectivo", "CUP"), ("transferencia", "CUP")}
    assert sum(x["amount_usd_equiv"] for x in g) == pytest.approx(float(agosto["bruto"]), rel=0.05)
    assert sum(x["share_pct"] for x in g) == pytest.approx(100, abs=0.5)


def test_a04_comparacion_periodo_anterior(tool):
    d = tool("get_sales_summary", {**AGO, "compare": "previous_period"})["data"]
    c = d["comparison"]
    assert c["period"] == {"from": "2026-07-01", "to": "2026-07-31"}
    esperado = round((d["totals"]["net_usd"] - c["totals"]["net_usd"]) / c["totals"]["net_usd"] * 100, 1)
    assert c["delta_pct"]["net_usd"] == pytest.approx(esperado, abs=0.1)


def test_a05_a06_top_productos(tool, sql):
    u = tool("get_top_products", {**AGO, "metric": "units", "limit": 1})["data"]["items"][0]
    sku_u, uds = sql("select p.sku, sum(lv.cantidad) from lineas_venta lv join ventas v on v.id=lv.venta_id join productos p on p.id=lv.producto_id"
                     " where v.estado='completada' and v.fecha >= %s and v.fecha < %s group by 1 order by 2 desc limit 1", (INI, FIN))[0]
    assert (u["sku"], u["units"]) == (sku_u, int(uds))
    r = tool("get_top_products", {**AGO, "metric": "revenue", "limit": 3})["data"]["items"]
    assert r[0]["revenue_usd"] >= r[1]["revenue_usd"] >= r[2]["revenue_usd"]


def test_a07_productos_sin_ventas(tool):
    items = tool("get_top_products", {"from": "2026-09-01", "to": "2026-09-30", "order": "bottom",
                                      "include_zero_sales": True, "limit": 20})["data"]["items"]
    ceros = {i["sku"] for i in items if i["units"] == 0}
    assert {"ELE-003", "ELE-011", "MOV-003"} <= ceros


def test_a08_a10_busqueda(tool):
    a = tool("find_products", {"query": "aceite"})["data"]
    assert a["ambiguous"] is True and {"GRA-010", "GRA-011"} <= skus(a["matches"])
    b = tool("find_products", {"query": "aseite jirasol"})["data"]
    assert b["matches"][0]["sku"] == "GRA-010"
    c = tool("find_products", {"query": "ventilador grande", "limit": 10})["data"]
    assert {"CLI-001", "CLI-002", "CLI-003"} <= skus(c["matches"]) and all(m["active"] for m in c["matches"])
    assert tool("find_products", {"query": "GRA-013"})["data"]["matches"][0]["sku"] == "GRA-013"
    assert tool("find_products", {"query": "zzqqxx"})["status"] == "no_data"


def test_a11_aceite_agotado(tool):
    p = tool("get_product", {"sku": "GRA-010"})["data"]
    assert (p["stock"], p["status"], p["priority"], p["pending_purchases"]) == (0, "agotado", True, [])
    assert p["price_cup_today"] % 10 == 0


def test_a12_margen_cafe(tool):
    assert tool("get_product", {"sku": "gra-013"})["data"]["margin_30d_pct"] < 10


def test_a13_agotados(tool):
    d = tool("get_inventory_status", {"filter": "out_of_stock"})["data"]
    assert {"GRA-010", "ENE-004"} <= skus(d["items"])
    assert all(i["status"] == "agotado" for i in d["items"])
    assert not {"TEC-005", "ELE-014", "BEB-010"} & skus(d["items"])       # inactivos fuera


def test_a14_riesgo_rotura(tool):
    d = tool("get_inventory_status", {"filter": "all_issues"})["data"]
    estado = {i["sku"]: i["status"] for i in d["items"]}
    assert estado.get("GRA-012") in ("riesgo_rotura", "agotado")
    riesgo = [i for i in d["items"] if i["status"] == "riesgo_rotura"]
    assert all((i["stock"] + i["pending_qty"]) / i["velocity_30d"] < i["lead_time_days"] for i in riesgo)


def test_a15_exceso(tool):
    d = tool("get_inventory_status", {"filter": "overstock"})["data"]
    assert {"CLI-001", "CLI-004", "TEC-002", "FER-010"} <= skus(d["items"])
    assert all(i["coverage_days"] > 90 for i in d["items"])
    assert d["totals"]["immobilized_value_usd"] > 0


def test_a16_sin_movimiento(tool):
    assert {"ELE-003", "ELE-011", "MOV-003"} <= skus(tool("get_inventory_status", {"filter": "no_movement"})["data"]["items"])


def test_a17_margen_bajo(tool):
    d = tool("get_margin_analysis", {"from": "2026-09-01", "to": "2026-09-30", "group_by": "product", "below_threshold_pct": 10})["data"]
    claves = {i["key"] for i in d["items"]}
    assert {"GRA-013", "GRA-014"} <= claves and all(i["margin_pct"] < 10 for i in d["items"])


def test_a18_alertas(tool):
    d = tool("get_alerts")["data"]
    por_regla = {(a["rule"], (a["product"] or {}).get("sku")): a for a in d["alerts"]}
    assert por_regla[("agotado_prioritario", "GRA-010")]["priority"] == "urgent"
    assert ("devoluciones_anomalas", "ELE-002") in por_regla
    assert ("producto_sin_precio", "ASE-016") in por_regla
    niveles = ["urgent", "high", "medium", "low"]
    orden = [niveles.index(a["priority"]) for a in d["alerts"]]
    assert orden == sorted(orden)
    assert all(a["alert_key"].endswith("2026-09-30") for a in d["alerts"])
    solo = tool("get_alerts", {"min_priority": "urgent"})["data"]["alerts"]
    assert solo and all(a["priority"] == "urgent" for a in solo)


def test_a19_anulaciones_semana(tool):
    assert tool("get_returns_and_voids", {"from": "2026-09-21", "to": "2026-09-27"})["data"]["voids"]["pct_of_tickets"] > 3


def test_a20_devoluciones_olla(tool):
    d = tool("get_returns_and_voids", {"from": "2026-08-31", "to": "2026-09-30"})["data"]["returns"]
    olla = next(p for p in d["by_product"] if p["sku"] == "ELE-002")
    assert olla["return_pct"] > 5 and olla["top_reason"] == "Producto defectuoso"


def test_a21_tasa(tool, sql):
    d = tool("get_exchange_rate", AGO)["data"]
    assert len(d["series"]) == 31
    assert Decimal(str(d["series"][0]["usd_cup"])) == sql("select usd_cup from tasas_cambio where fecha='2026-08-01'")[0][0]


def test_a22_calidad_datos(tool):
    d = tool("get_data_quality")["data"]
    assert "ASE-016" in skus(d["active_without_price"])
    assert skus(d["inactive_with_stock"]) & {"TEC-005", "ELE-014", "BEB-010"}
    assert d["stock_mismatch_count"] == 0


def test_a23_caida_ayer(tool, sql):
    d = tool("get_business_summary", {"date": "2026-09-29"})["data"]
    assert d["is_partial_day"] is False
    # Lo esperado = media de los 4 martes anteriores (día completo), calculado por otro camino.
    neto = lambda dia: float(sql(
        "select coalesce((select sum(total_usd) from ventas where estado='completada' and (fecha at time zone 'America/Havana')::date = %s),0)"
        " - coalesce((select sum(reembolso_usd) from devoluciones where (fecha at time zone 'America/Havana')::date = %s),0)", (dia, dia))[0][0])
    esperado = sum(neto(f"2026-09-{n:02d}") for n in (1, 8, 15, 22)) / 4
    assert d["expected"]["net_usd"] == pytest.approx(esperado, abs=0.01)
    assert d["vs_expected_pct"] == pytest.approx((neto("2026-09-29") - esperado) / esperado * 100, abs=0.1)
    assert d["vs_expected_pct"] < -20                                   # caída sembrada en los datos de demostración


def test_resumen_hoy_parcial(tool):
    d = tool("get_business_summary")["data"]
    assert d["date"] == "2026-09-30" and d["is_partial_day"] is True and d["as_of_hour"] == "11:30"


@pytest.mark.parametrize("nombre,params", [
    ("get_sales_summary", {"from": "2025-01-01", "to": "2026-06-01"}),          # A24 rango > 400 días
    ("get_top_products", {**AGO, "limit": 500}),                                  # A25 límite
    ("get_sales_summary", {**AGO, "group_by": "proveedor"}),
    ("get_sales_summary", {**AGO, "tabla": "ventas"}),                            # parámetro desconocido
    ("get_sales_summary", {"from": "2026-13-01", "to": "2026-08-31"}),
    ("get_business_summary", {"date": "2026-12-31"}),                             # futuro
])
def test_a24_a25_parametros_invalidos(tool, nombre, params):
    r = tool(nombre, params)
    assert r["status"] == "error" and r["error_code"] == "invalid_params"


def test_a26_no_encontrado(tool):
    r = tool("get_product", {"sku": "NOEXISTE"})
    assert r["status"] == "error" and r["error_code"] == "not_found" and "SQL" not in r["message"]


def test_festivo_tienda_cerrada(tool):
    d = tool("get_sales_summary", {"from": "2025-12-25", "to": "2025-12-25", "group_by": "channel"})["data"]
    tickets = {g["key"]: g["tickets"] for g in d["groups"]}
    assert tickets.get("tienda_fisica", 0) == 0 and tickets["web"] > 0     # puede haber devoluciones, no ventas
