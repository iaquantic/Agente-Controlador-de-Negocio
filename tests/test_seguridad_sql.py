"""Bloque C (base de datos): el rol del agente es de solo lectura por construcción."""
from __future__ import annotations

import json

import psycopg
import pytest


@pytest.mark.parametrize("sentencia", [
    "insert into public.ventas (negocio_id, numero, canal, fecha, estado, tasa_usd_cup, total_usd, total_cup) values (1,'X','web',now(),'completada',1,1,1)",
    "update public.precios_producto set precio_usd = 1",
    "delete from public.ventas",
    "select * from public.ventas limit 1",                       # C02: ni siquiera lectura directa de tablas
    "select * from registro.interacciones limit 1",              # C03
    "select agente._productos()",                                # funciones internas no expuestas
    "create table agente.x (a int)",
    "update agente.parametros set valor = 0",
])
def test_c01_c03_sin_escritura_ni_tablas(lectura, sentencia):
    with pytest.raises(psycopg.Error):
        lectura.execute(sentencia)


def test_transacciones_solo_lectura(lectura):
    assert lectura.execute("show transaction_read_only").fetchone()[0] == "on"
    assert lectura.execute("show statement_timeout").fetchone()[0] == "10s"


def test_c04_timeout(lectura):
    with pytest.raises(psycopg.errors.QueryCanceled):
        lectura.execute("select pg_sleep(11)")


def test_c05_inyeccion_como_texto(lectura, sql):
    antes = sql("select count(*) from ventas")[0][0]
    r = lectura.execute("select agente.get_product(%s::jsonb)", (json.dumps({"sku": "x'; drop table ventas;--"}),)).fetchone()[0]
    assert r["status"] == "error"
    assert sql("select count(*) from ventas")[0][0] == antes


def test_api_publica_sin_acceso(sql):
    # Ningún rol distinto de agente_lectura/agente_owner puede ejecutar las herramientas.
    filas = sql("select r.rolname from pg_roles r where has_function_privilege(r.oid, 'agente.get_sales_summary(jsonb)', 'execute')"
                " and r.rolname not in ('agente_lectura', 'agente_owner') and not r.rolsuper")
    assert filas == []
