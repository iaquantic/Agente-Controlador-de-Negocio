"""Importador contra PostgreSQL: esquema desde cero, permisos del rol importador y lectura por las herramientas.

Crea una base de datos propia (`importador_prueba`) en el servidor de pruebas; no toca la de demostración.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
import pytest

from agente_interno.importador import __main__ as cli
from agente_interno.importador import preparar
from agente_interno.importador.escritura import escribir

from .datos_importacion import generar
from .test_importador import AHORA, EJEMPLO

SERVIDOR = os.environ.get("TEST_DB_URL_SERVIDOR", "host=/var/tmp/pgtest port=55432 user=postgres dbname=postgres")
BD = "importador_prueba"


def _url(**cambios) -> str:
    partes = dict(p.split("=", 1) for p in SERVIDOR.split())
    partes.update(cambios)
    return " ".join(f"{k}={v}" for k, v in partes.items())


@pytest.fixture(scope="module")
def base():
    try:
        servidor = psycopg.connect(SERVIDOR, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL de pruebas no disponible: {e}")
    with servidor:
        servidor.execute(f"drop database if exists {BD} with (force)")
        servidor.execute(f"create database {BD}")
    assert cli.main(["instalar-esquema", "--db", _url(dbname=BD)]) == 0
    with psycopg.connect(_url(dbname=BD), autocommit=True) as admin:
        admin.execute("alter role agente_importador login")
        admin.execute("alter role agente_lectura login")
    yield
    with psycopg.connect(SERVIDOR, autocommit=True) as servidor:
        servidor.execute(f"drop database if exists {BD} with (force)")


@pytest.fixture
def importador(base):
    with psycopg.connect(_url(dbname=BD, user="agente_importador"), autocommit=True) as c:
        yield c


@pytest.fixture
def tool(base):
    with psycopg.connect(_url(dbname=BD, user="agente_lectura"), autocommit=True) as c:
        c.execute("select set_config('agente.ahora', %s, false)", (AHORA.isoformat(),))
        yield lambda nombre, p=None: c.execute(f"select agente.{nombre}(%s::jsonb)", (json.dumps(p or {}),)).fetchone()[0]


def _importar(conn, carpeta: Path, negocio: str | None = "Bodega La Esquina"):
    carga, inf = preparar(carpeta, AHORA, conn)
    assert inf.errores == []
    return escribir(conn, carga, negocio)


def test_instalar_esquema_es_idempotente(base, capsys):
    assert cli.main(["instalar-esquema", "--db", _url(dbname=BD)]) == 0
    assert capsys.readouterr().out.count("ya aplicada") == 5


def test_ejemplo_importado_lo_leen_las_herramientas(importador, tool):
    n = _importar(importador, EJEMPLO)
    assert n["ventas"] == 16 and n["inventario"] == 8

    calidad = tool("get_data_quality")["data"]
    assert calidad["stock_mismatch_count"] == 0
    assert calidad["active_without_price"] == [] and calidad["last_sale_at"] == "2026-10-04T18:10:00-04:00"

    ventas = tool("get_sales_summary", {"from": "2026-09-01", "to": "2026-10-04"})["data"]["totals"]
    assert ventas["gross_usd"] == 394.25 - 6.0     # el ticket anulado (5 × 1,20) no cuenta
    assert ventas["voided_tickets"] == 1 and ventas["returns_usd"] == 65.0

    pollo = tool("get_product", {"sku": "POL-10LB"})["data"]
    assert pollo["price_usd"] == 14.0 and pollo["stock"] == 8 and pollo["category"] == "Alimentos"

    stock = {i["sku"]: i for i in tool("get_inventory_status", {"filter": "all_issues"})["data"]["items"]}
    assert stock["VEN-18"]["lead_time_days"] == 21     # configuración de categorias.csv
    assert tool("get_exchange_rate", {"from": "2026-09-01", "to": "2026-10-05"})["data"]["today"]["usd_cup"] == 752.0
    pendientes = tool("get_product", {"sku": "ACE-1L"})["data"]
    assert pendientes["pending_purchases"][0]["quantity"] == 24


def test_reimportar_da_el_mismo_resultado_y_conserva_ids(importador):
    consulta = ("select (select count(*) from ventas), (select sum(total_usd) from ventas), "
                "(select count(*) from movimientos_inventario), "
                "(select string_agg(p.sku || ':' || p.id || ':' || i.stock_actual, ' ' order by p.sku) "
                " from productos p join inventario i on i.producto_id = p.id)")
    _importar(importador, EJEMPLO)
    antes = importador.execute(consulta).fetchone()
    _importar(importador, EJEMPLO)
    assert importador.execute(consulta).fetchone() == antes


def test_producto_que_desaparece_queda_inactivo(importador, tool, tmp_path):
    for f in EJEMPLO.iterdir():
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    # Si siguiera en ventas o compras, se volvería a crear (en «Sin categoría»).
    for nombre in ("productos.csv", "ventas.csv", "compras.csv", "inventario.csv"):
        t = (tmp_path / nombre).read_text(encoding="utf-8").splitlines()
        (tmp_path / nombre).write_text("\n".join(l for l in t if "JAB-3" not in l), encoding="utf-8")
    _importar(importador, tmp_path)
    jabon = importador.execute("select p.activo, i.stock_actual from productos p join inventario i on i.producto_id = p.id "
                               "where sku = 'JAB-3'").fetchone()
    assert jabon == (False, 0)
    assert tool("get_data_quality")["data"]["stock_mismatch_count"] == 0
    _importar(importador, EJEMPLO)


def test_el_importador_no_ve_el_registro_ni_ejecuta_herramientas(importador):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        importador.execute("select * from registro.interacciones")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        importador.execute("select agente.get_data_quality('{}')")


def test_un_anio_de_ventas(importador, tool, tmp_path):
    datos = generar(tmp_path, productos=40, dias=120, tickets_dia=15)
    with psycopg.connect(_url(dbname=BD), autocommit=True) as admin:     # el importador no puede borrar tasas
        admin.execute("delete from tasas_cambio")
    carga, inf = preparar(tmp_path, AHORA, importador)
    assert inf.errores == []
    escribir(importador, carga, "Bodega La Esquina")
    assert importador.execute("select count(*) from ventas").fetchone()[0] == datos["tickets"]
    assert tool("get_data_quality")["data"]["stock_mismatch_count"] == 0
    resumen = tool("get_business_summary")
    assert resumen["status"] == "ok" and resumen["data"]["month_to_date"]["tickets"] > 0
    mes = tool("get_sales_summary", {"from": "2026-09-01", "to": "2026-09-30"})["data"]["totals"]
    esperado = sum(t.total_usd for t in carga.tickets if t.estado == "completada" and t.fecha.month == 9)
    assert abs(mes["gross_usd"] - float(esperado)) < 0.01
    # Sin stock negativo en ningún momento de la historia.
    negativos = importador.execute(
        "select count(*) from (select sum(cantidad) over (partition by producto_id order by fecha, id) s "
        "from movimientos_inventario) x where s < 0").fetchone()[0]
    assert negativos == 0
    _importar(importador, EJEMPLO)
