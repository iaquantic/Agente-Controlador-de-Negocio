"""API interna para el futuro Agente Orquestador (08_contrato_orquestador.md, v1.0)."""
from __future__ import annotations

import hmac
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator

from .agente import AgenteInterno
from .registro import Registro
from .tiempo import Reloj

ESQUEMAS = Path(__file__).resolve().parent.parent / "docs" / "especificacion" / "schemas"
VALIDAR_PETICION = Draft202012Validator(json.loads((ESQUEMAS / "orquestador_request.schema.json").read_text()))
VALIDAR_RESPUESTA = Draft202012Validator(json.loads((ESQUEMAS / "orquestador_response.schema.json").read_text()))
CACHE_S = 300


def _metrica(valor, unidad: str, tipo: str, definicion: str | None = None, cup=None) -> dict:
    m = {"value": float(valor) if valor is not None else None, "unit": unidad, "kind": tipo}
    if definicion:
        m["definition"] = definicion
    if cup is not None:
        m["value_cup"] = float(cup)
    return m


def _alertas(res: dict) -> list[dict]:
    out = []
    for i, a in enumerate(res.get("data", {}).get("alerts", []), 1):
        out.append({"id": f"A{i}", **{k: a[k] for k in ("alert_key", "rule", "priority", "category", "product", "title",
                                                         "detail", "current_value", "threshold", "detected_at")}})
    return out


def _cifra(x) -> str:
    return f"{float(x):,.2f}".replace(",", " ").replace(".", ",")


def _pct_txt(x) -> str:
    return f"{float(x):+.1f}".replace(".", ",")


class Informes:
    """Informes predefinidos construidos de forma determinista a partir de las herramientas."""

    def __init__(self, db, reloj: Reloj):
        self.db, self.reloj = db, reloj

    async def _h(self, nombre: str, params: dict, usadas: list[str]) -> dict:
        res, _ = await self.db.herramienta(nombre, params)
        usadas.append(nombre)
        return res

    async def generar(self, tipo: str, desde: date, hasta: date) -> tuple[dict, list[str]]:
        u: list[str] = []
        per = {"from": desde.isoformat(), "to": hasta.isoformat()}
        metrics: dict[str, Any] = {}
        findings: list[dict] = []
        alerts: list[dict] = []

        if tipo == "estado_general":
            bs = await self._h("get_business_summary", {"date": hasta.isoformat()}, u)
            al = await self._h("get_alerts", {"min_priority": "high"}, u)
            d = bs["data"]
            metrics = {
                "ventas_netas_dia_usd": _metrica(d["today"]["net_usd"], "USD", "calculation", "completadas − devoluciones, hasta la hora indicada", d["today"]["net_cup"]),
                "variacion_vs_esperado_pct": _metrica(d["vs_expected_pct"], "%", "calculation", d["expected"]["basis"]),
                "ventas_netas_mes_usd": _metrica(d["month_to_date"]["net_usd"], "USD", "calculation", None, d["month_to_date"]["net_cup"]),
                "tickets_dia": _metrica(d["today"]["tickets"], "ventas", "fact"),
                "tasa_usd_cup": _metrica(d["fx_today"], "CUP/USD", "fact"),
            }
            alerts = _alertas(al)
            resumen = (f"Hoy hasta las {d['as_of_hour']}: {_cifra(d['today']['net_usd'])} USD en {d['today']['tickets']} ventas "
                       f"({_pct_txt(d['vs_expected_pct'])} % frente a lo esperado). {len(alerts)} alertas urgentes o altas.") \
                if d["vs_expected_pct"] is not None else f"Hoy: {_cifra(d['today']['net_usd'])} USD. {len(alerts)} alertas urgentes o altas."
        elif tipo == "ventas":
            ss = await self._h("get_sales_summary", {**per, "group_by": "channel", "compare": "previous_period"}, u)
            tp = await self._h("get_top_products", {**per, "metric": "revenue", "limit": 5}, u)
            t, c = ss["data"]["totals"], ss["data"]["comparison"]
            metrics = {
                "ventas_netas_usd": _metrica(t["net_usd"], "USD", "calculation", "completadas − devoluciones", t["net_cup"]),
                "tickets": _metrica(t["tickets"], "ventas", "fact"),
                "ticket_medio_usd": _metrica(t["avg_ticket_usd"], "USD", "calculation"),
                "margen_bruto_pct": _metrica(t["gross_margin_pct"], "%", "calculation", "(ventas netas − coste) ÷ ventas netas"),
                "variacion_ventas_pct": _metrica(c["delta_pct"]["net_usd"], "%", "calculation", "frente al periodo anterior"),
            }
            for i, g in enumerate(ss["data"]["groups"], 1):
                findings.append({"id": f"C{i}", "kind": "calculation", "category": "ventas", "title": f"Canal {g['key']}",
                                 "detail": f"{_cifra(g['net_usd'])} USD en {g['tickets']} ventas.", "evidence": g})
            for p in (tp.get("data") or {}).get("items", []):
                findings.append({"id": f"P{p['rank']}", "kind": "calculation", "category": "ventas",
                                 "title": f"Top {p['rank']} por ingresos: {p['name']}",
                                 "detail": f"{_cifra(p['revenue_usd'])} USD ({p['share_pct']} % del total).", "evidence": p})
            resumen = f"Ventas netas {_cifra(t['net_usd'])} USD ({_pct_txt(c['delta_pct']['net_usd'])} % frente al periodo anterior)." \
                if c["delta_pct"]["net_usd"] is not None else f"Ventas netas {_cifra(t['net_usd'])} USD."
        elif tipo == "inventario":
            inv = await self._h("get_inventory_status", {"filter": "all_issues"}, u)
            al = await self._h("get_alerts", {"category": "inventario", "min_priority": "high"}, u)
            tot = inv["data"]["totals"]
            metrics = {f"productos_{k}": _metrica(v, "productos", "calculation") for k, v in tot["by_status"].items()}
            metrics["dinero_inmovilizado_usd"] = _metrica(tot["immobilized_value_usd"], "USD", "calculation",
                                                          "stock × coste medio de productos en exceso o sin movimiento")
            metrics["valor_stock_usd"] = _metrica(tot["total_stock_value_usd"], "USD", "calculation")
            for i, it in enumerate(inv["data"]["items"][:15], 1):
                findings.append({"id": f"F{i}", "kind": "calculation", "category": "inventario",
                                 "title": f"{it['name']}: {it['status'].replace('_', ' ')}",
                                 "detail": f"Stock {it['stock']} u; cobertura {it['coverage_days']} días; plazo {it['lead_time_days']} días.",
                                 "evidence": it})
            alerts = _alertas(al)
            b = tot["by_status"]
            resumen = (f"{b['agotado']} agotados, {b['riesgo_rotura']} en riesgo de rotura, {b['stock_bajo']} con stock bajo; "
                       f"{_cifra(tot['immobilized_value_usd'])} USD inmovilizados en exceso o sin movimiento.")
        elif tipo == "rentabilidad":
            cat = await self._h("get_margin_analysis", {**per, "group_by": "category", "order": "desc"}, u)
            baj = await self._h("get_margin_analysis", {**per, "group_by": "product", "below_threshold_pct": 10}, u)
            metrics = {"margen_bruto_pct": _metrica(cat["data"]["overall_margin_pct"], "%", "calculation",
                                                    "(ventas netas − coste) ÷ ventas netas")}
            for it in cat["data"]["items"]:
                metrics[f"margen_{it['key']}_pct"] = _metrica(it["margin_pct"], "%", "calculation")
            for i, it in enumerate(baj["data"]["items"], 1):
                findings.append({"id": f"M{i}", "kind": "calculation", "category": "rentabilidad",
                                 "title": f"Margen bajo: {it['name']}", "detail": f"{it['margin_pct']} % (antes {it['margin_prev_period_pct']} %).",
                                 "evidence": it})
            resumen = f"Margen bruto del periodo: {cat['data']['overall_margin_pct']} %. {len(findings)} productos por debajo del 10 %."
        elif tipo == "alertas":
            al = await self._h("get_alerts", {}, u)
            alerts = _alertas(al)
            n = al["data"]["count_by_priority"]
            resumen = f"{len(alerts)} alertas activas: {n['urgent']} urgentes, {n['high']} altas, {n['medium']} medias, {n['low']} bajas."
        else:  # calidad_datos
            dq = await self._h("get_data_quality", {}, u)
            d = dq["data"]
            metrics = {"minutos_desde_ultimo_dato": _metrica(d["freshness_minutes"], "min", "calculation"),
                       "descuadres_stock": _metrica(d["stock_mismatch_count"], "productos", "fact")}
            for i, p in enumerate(d["active_without_price"], 1):
                findings.append({"id": f"Q{i}", "kind": "fact", "category": "calidad_datos",
                                 "title": f"{p['name']} activo sin precio", "evidence": p})
            resumen = f"Último dato hace {d['freshness_minutes']} min; {len(d['active_without_price'])} productos activos sin precio."
        return {"summary": resumen, "metrics": metrics, "findings": findings, "alerts": alerts}, u


def _extraer_json(texto: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", texto or "")
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def crear_app(db, agente: AgenteInterno | None, registro: Registro, reloj: Reloj, token: str) -> FastAPI:
    app = FastAPI(title="Agente Interno · API para el orquestador", version="1.0", docs_url=None, redoc_url=None)
    informes = Informes(db, reloj)
    cache: dict[tuple, tuple[float, dict]] = {}

    def _base(req: dict, status: str) -> dict:
        return {"request_id": req.get("request_id", ""), "version": "1.0", "status": status}

    def _error(req: dict, http: int, codigo: str, mensaje: str) -> JSONResponse:
        cuerpo = {**_base(req, "error"), "error": {"code": codigo, "message": mensaje},
                  "generated_at": reloj.ahora().isoformat(timespec="seconds")}
        return JSONResponse(cuerpo, status_code=http)

    @app.post("/v1/consulta")
    async def consulta(request: Request, authorization: str | None = Header(default=None)):
        inicio = time.monotonic()
        try:
            req = await request.json()
        except Exception:
            req = {}
        if not isinstance(req, dict):
            req = {}
        esperado = f"Bearer {token}"
        if not authorization or not hmac.compare_digest(authorization.encode(), esperado.encode()):
            return _error(req, 401, "unauthorized", "Token no válido.")
        if req.get("version") not in (None, "1.0") and isinstance(req.get("version"), str):
            return _error(req, 409, "unsupported_version", "Versión del contrato no soportada; usa 1.0.")
        fallos = list(VALIDAR_PETICION.iter_errors(req))
        if fallos:
            return _error(req, 400, "invalid_request", f"Petición no válida: {fallos[0].message}")

        hoy = reloj.ahora().date()
        periodo = req.get("period") or {}
        desde = date.fromisoformat(periodo["from"]) if periodo else (hoy.replace(day=1) if req.get("report") not in ("estado_general", "alertas", "calidad_datos") else hoy)
        hasta = date.fromisoformat(periodo["to"]) if periodo else hoy
        herramientas: list[str] = []
        try:
            if req["type"] == "report":
                clave = (req["report"], desde, hasta)
                if clave in cache and time.monotonic() - cache[clave][0] < CACHE_S:
                    cuerpo = {**cache[clave][1], "request_id": req["request_id"]}
                    return JSONResponse(cuerpo)
                partes, herramientas = await informes.generar(req["report"], desde, hasta)
                cuerpo = {**_base(req, "ok"), **partes}
            elif req["type"] == "tool":
                res, _ = await db.herramienta(req["tool"]["name"], req["tool"].get("params") or {})
                herramientas = [req["tool"]["name"]]
                estado = {"ok": "ok", "no_data": "no_data"}.get(res.get("status"), "partial")
                cuerpo = {**_base(req, estado), "summary": res.get("message") or f"Resultado de {req['tool']['name']}.",
                          "metrics": {}, "findings": [], "alerts": [], "tool_result": res.get("data")}
                if res.get("period"):
                    desde, hasta = date.fromisoformat(res["period"]["from"]), date.fromisoformat(res["period"]["to"])
            else:
                if agente is None:
                    return _error(req, 500, "internal", "El modelo no está configurado.")
                r = await agente.responder(f"orq:{req['request_id']}", req["question"], canal="orquestador", conservar=False)
                herramientas = [t["name"] for t in r.herramientas]
                datos = _extraer_json(r.texto) or {}
                estado = datos.get("status") if datos.get("status") in ("ok", "partial", "no_data", "out_of_scope") else "partial"
                cuerpo = {**_base(req, estado), "summary": datos.get("summary") or r.texto[:500],
                          "metrics": datos.get("metrics") or {}, "findings": datos.get("findings") or [],
                          "alerts": datos.get("alerts") or [], "not_available": datos.get("not_available") or []}
        except Exception:
            return _error(req, 500, "internal", "No se pudo completar la consulta.")

        dq, _ = await db.herramienta("get_data_quality", {})
        dqd = dq.get("data") or {}
        cuerpo.setdefault("not_available", [])
        cuerpo.update({
            "period": {"from": desde.isoformat(), "to": hasta.isoformat(), "timezone": "America/Havana"},
            "data_quality": {"last_data_at": dqd.get("last_sale_at"), "freshness_minutes": dqd.get("freshness_minutes"),
                             "fx": dq.get("fx"), "warnings": dq.get("warnings", [])},
            "tools_used": herramientas,
            "generated_at": reloj.ahora().isoformat(timespec="seconds"),
        })
        if not VALIDAR_RESPUESTA.is_valid(cuerpo):        # nunca devolver algo fuera de contrato
            primero = next(VALIDAR_RESPUESTA.iter_errors(cuerpo))
            cuerpo = {**_base(req, "partial"), "summary": cuerpo.get("summary", ""), "metrics": {}, "findings": [],
                      "alerts": [], "not_available": [{"item": "respuesta estructurada", "reason": primero.message[:200]}],
                      **{k: cuerpo[k] for k in ("period", "data_quality", "tools_used", "generated_at")}}
        if req["type"] == "report":
            cache[(req["report"], desde, hasta)] = (time.monotonic(), cuerpo)
        await registro.interaccion(canal="orquestador", usuario_id="orquestador", autorizado=True,
                                   entrada=json.dumps(req, ensure_ascii=False)[:2000],
                                   herramientas=[{"name": h} for h in herramientas],
                                   latencia_ms=int((time.monotonic() - inicio) * 1000), tokens=None,
                                   respuesta=cuerpo.get("summary"), estado=cuerpo["status"])
        return JSONResponse(cuerpo)

    return app
