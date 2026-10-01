"""Bloque D (orquestador): contrato v1.0 contra la base de datos local."""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace as NS

import httpx
import pytest

from agente_interno.agente import AgenteInterno
from agente_interno.db import BaseDatos
from agente_interno.orquestador import VALIDAR_RESPUESTA, crear_app
from agente_interno.registro import Registro
from agente_interno.tiempo import Reloj

from .conftest import AHORA, URL_AGENTE
from .test_servicio import ClaudeFalso, respuesta, texto

TOKEN = "token-de-prueba"
CAB = {"Authorization": f"Bearer {TOKEN}"}


def peticion(**k):
    return {"request_id": "5b1c0f3e-7d7a-4f55-9a0e-2c9a1c1d8f10", "version": "1.0",
            "requested_at": "2026-09-30T19:30:00-04:00", **k}


@pytest.fixture
async def cliente(tmp_path, lectura):          # `lectura` hace que se salte si no hay BD
    reloj = Reloj(datetime.fromisoformat(AHORA))
    db = BaseDatos(URL_AGENTE, reloj)
    await db.abrir()
    registro = Registro(None, str(tmp_path / "r.jsonl"))
    await registro.abrir()
    claude = ClaudeFalso([respuesta([texto(json.dumps({
        "status": "ok", "summary": "El refresco de lata es el más vendido.",
        "findings": [{"id": "F1", "kind": "fact", "category": "ventas", "title": "Refresco de lata"}]}))], "end_turn")])
    agente = AgenteInterno(db, reloj, cliente=claude)
    app = crear_app(db, agente, registro, reloj, TOKEN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await db.cerrar()


async def test_d11_informe_inventario(cliente):
    r = await cliente.post("/v1/consulta", json=peticion(type="report", report="inventario"), headers=CAB)
    assert r.status_code == 200
    b = r.json()
    assert VALIDAR_RESPUESTA.is_valid(b), list(VALIDAR_RESPUESTA.iter_errors(b))[:1]
    assert b["status"] == "ok" and b["request_id"] == "5b1c0f3e-7d7a-4f55-9a0e-2c9a1c1d8f10"
    assert any(a["rule"] == "agotado_prioritario" and a["product"]["sku"] == "GRA-010" for a in b["alerts"])
    assert b["metrics"]["dinero_inmovilizado_usd"]["kind"] == "calculation"
    assert set(b["tools_used"]) == {"get_inventory_status", "get_alerts"}


@pytest.mark.parametrize("informe", ["estado_general", "ventas", "rentabilidad", "alertas", "calidad_datos"])
async def test_informes_validos(cliente, informe):
    r = await cliente.post("/v1/consulta", json=peticion(type="report", report=informe,
                                                         period={"from": "2026-09-01", "to": "2026-09-30"}), headers=CAB)
    b = r.json()
    assert r.status_code == 200 and b["status"] == "ok" and VALIDAR_RESPUESTA.is_valid(b)
    assert b["summary"] and "<b>" not in b["summary"]


async def test_d12_pregunta(cliente):
    r = await cliente.post("/v1/consulta", json=peticion(type="question", question="¿Qué productos se venden más?"), headers=CAB)
    b = r.json()
    assert r.status_code == 200 and VALIDAR_RESPUESTA.is_valid(b) and b["findings"][0]["kind"] == "fact"


async def test_d13_herramienta_directa(cliente):
    r = await cliente.post("/v1/consulta", json=peticion(type="tool", tool={"name": "get_sales_summary",
                                                                             "params": {"from": "2026-08-01", "to": "2026-08-31"}}), headers=CAB)
    b = r.json()
    assert b["status"] == "ok" and b["tool_result"]["totals"]["net_usd"] > 0
    assert b["period"] == {"from": "2026-08-01", "to": "2026-08-31", "timezone": "America/Havana"}


async def test_c12_sin_token(cliente):
    r = await cliente.post("/v1/consulta", json=peticion(type="report", report="alertas"))
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    r = await cliente.post("/v1/consulta", json=peticion(type="report", report="alertas"), headers={"Authorization": "Bearer x"})
    assert r.status_code == 401


async def test_d15_version(cliente):
    r = await cliente.post("/v1/consulta", json=peticion(type="report", report="alertas", version="2.0"), headers=CAB)
    assert r.status_code == 409 and r.json()["error"]["code"] == "unsupported_version"


async def test_peticion_invalida(cliente):
    r = await cliente.post("/v1/consulta", json=peticion(type="report"), headers=CAB)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    r = await cliente.post("/v1/consulta", json=peticion(type="tool", tool={"name": "drop_table"}), headers=CAB)
    assert r.status_code == 400


async def test_d16_cache(cliente):
    p = peticion(type="report", report="alertas")
    a = (await cliente.post("/v1/consulta", json=p, headers=CAB)).json()
    b = (await cliente.post("/v1/consulta", json={**p, "request_id": "otra"}, headers=CAB)).json()
    assert a["generated_at"] == b["generated_at"] and b["request_id"] == "otra"
