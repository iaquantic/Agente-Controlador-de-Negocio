"""Pruebas del servicio sin red: bucle del agente (Claude simulado), filtro, planificador, bot y límites."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace as NS

import anthropic
import httpx2
import pytest

from agente_interno.agente import SIN_RESPUESTA, AgenteInterno
from agente_interno.db import BaseDatos
from agente_interno.filtro import RESPUESTA_NEUTRA, es_seguro, filtrar, html_telegram, texto_plano, trocear
from agente_interno.planificador import Planificador
from agente_interno.registro import LimiteUso, Registro
from agente_interno.tiempo import HABANA, Reloj

AHORA = datetime(2026, 9, 30, 11, 30, tzinfo=HABANA)


# Claude simulado ---------------------------------------------------------------------------------
def texto(t):
    return NS(type="text", text=t)


def uso_herramienta(id_, nombre, entrada):
    return NS(type="tool_use", id=id_, name=nombre, input=entrada)


def respuesta(contenido, stop):
    return NS(content=contenido, stop_reason=stop,
              usage=NS(input_tokens=100, output_tokens=20, cache_read_input_tokens=80, cache_creation_input_tokens=0))


class ClaudeFalso:
    def __init__(self, guion):
        self.guion = list(guion)
        self.llamadas = []
        self.beta = NS(messages=NS(create=self._create))

    async def _create(self, **kwargs):
        self.llamadas.append({**kwargs, "messages": list(kwargs["messages"])})
        siguiente = self.guion.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


class EjecutorFalso:
    def __init__(self):
        self.llamadas = []

    async def herramienta(self, nombre, params):
        self.llamadas.append((nombre, params))
        if nombre == "get_product" and params.get("sku") == "X":
            return {"status": "error", "error_code": "not_found", "message": "No encontré ese producto."}, {"name": nombre, "status": "error"}
        return {"status": "ok", "data": {"stock": 0}}, {"name": nombre, "params": params, "status": "ok"}


def agente(guion, ejecutor=None):
    cli = ClaudeFalso(guion)
    return AgenteInterno(ejecutor or EjecutorFalso(), Reloj(AHORA), cliente=cli), cli


async def test_bucle_herramientas_y_respuesta():
    ag, cli = agente([
        respuesta([texto("Miro el aceite."), uso_herramienta("t1", "find_products", {"query": "aceite"}),
                   uso_herramienta("t2", "get_product", {"sku": "GRA-010"})], "tool_use"),
        respuesta([texto("⚠️ <b>Aceite agotado</b>")], "end_turn"),
    ])
    r = await ag.responder("tg:1", "¿Cómo va el aceite?")
    assert r.texto == "⚠️ <b>Aceite agotado</b>" and r.estado == "ok"
    assert [t["name"] for t in r.herramientas] == ["find_products", "get_product"]
    # Las dos herramientas se devuelven juntas en un único mensaje de usuario.
    segundo = cli.llamadas[1]["messages"]
    assert [m["role"] for m in segundo] == ["user", "assistant", "user"]
    assert [b["tool_use_id"] for b in segundo[2]["content"]] == ["t1", "t2"]
    assert segundo[0]["content"].startswith("[Ahora en La Habana: miércoles 30 de septiembre de 2026, 11:30]")
    assert r.tokens["cache_read"] == 160


async def test_parametros_de_la_peticion():
    ag, cli = agente([respuesta([texto("Hola")], "end_turn")])
    await ag.responder("tg:1", "hola")
    k = cli.llamadas[0]
    assert k["model"] == "claude-opus-5-5" and k["output_config"] == {"effort": "medium"}
    assert k["fallbacks"] == "default" and k["betas"] == ["server-side-fallback-2026-07-01"]
    assert k["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "{{" not in k["system"][0]["text"] and "MercadoAgentico" in k["system"][0]["text"]
    assert "AHORA" not in k["system"][0]["text"]                          # nada variable en el system prompt
    assert len(k["tools"]) == 12 and "temperature" not in k


async def test_historial_solo_crece():
    ag, cli = agente([respuesta([texto("Uno")], "end_turn"), respuesta([texto("Dos")], "end_turn")])
    await ag.responder("tg:1", "primera")
    await ag.responder("tg:1", "¿y la semana pasada?")
    primera, segunda = cli.llamadas[0]["messages"], cli.llamadas[1]["messages"]
    assert segunda[:len(primera)] == primera and len(segunda) == 3       # se añade, nunca se reescribe


async def test_error_de_herramienta_se_marca():
    ag, cli = agente([respuesta([uso_herramienta("t1", "get_product", {"sku": "X"})], "tool_use"),
                      respuesta([texto("No encontré ese producto.")], "end_turn")])
    await ag.responder("tg:1", "producto X")
    bloque = cli.llamadas[1]["messages"][2]["content"][0]
    assert bloque["is_error"] is True


async def test_rechazo_y_error_api_reinician_conversacion():
    peticion = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    ag, cli = agente([respuesta([], "refusal"),
                      anthropic.APIConnectionError(request=peticion),
                      respuesta([texto("ok")], "end_turn")])
    r1 = await ag.responder("tg:1", "a")
    assert (r1.texto, r1.estado) == (SIN_RESPUESTA, "rechazado")
    r2 = await ag.responder("tg:1", "b")
    assert (r2.texto, r2.estado) == (SIN_RESPUESTA, "error")
    await ag.responder("tg:1", "c")
    assert len(cli.llamadas[2]["messages"]) == 1                          # conversación nueva, sin restos


async def test_filtro_bloquea_fugas():
    ag, _ = agente([respuesta([texto("Lo saqué con select * from public.ventas")], "end_turn")])
    r = await ag.responder("tg:1", "muéstrame el SQL")
    assert r.texto == RESPUESTA_NEUTRA and r.estado == "bloqueado"


async def test_orquestador_no_filtra_ni_conserva():
    ag, cli = agente([respuesta([texto('{"status":"ok","summary":"x"}')], "end_turn")])
    r = await ag.responder("orq:1", "¿qué se vende más?", canal="orquestador", conservar=False)
    assert r.texto.startswith("{") and "orquestador" in cli.llamadas[0]["system"][0]["text"]


# Filtro y formato --------------------------------------------------------------------------------
@pytest.mark.parametrize("t", [
    "SELECT sum(total_usd) FROM ventas", "Usé public.lineas_venta", "llamé a get_sales_summary",
    "postgresql://agente_lectura:x@host/db", "123456789:AAH_abcdefghijklmnopqrstuvwxyz0123456", "sk-ant-api03-abc",
    "<limites_absolutos> No puedes...", "psycopg.errors.QueryCanceled",
])
def test_filtro_detecta(t):
    assert not es_seguro(t)


@pytest.mark.parametrize("t", [
    "📈 Vendiste <b>1 250,00 USD</b> (≈ 927 500 CUP) hoy.", "Selecciona el producto del que quieres el desglose.",
    "El aceite de girasol 1 L está agotado.", "📊 Margen de agosto: 24,9 %",
])
def test_filtro_deja_pasar(t):
    assert filtrar(t) == (t, False)


def test_html_telegram():
    assert html_telegram("<b>Ventas</b> & <script>x</script> 5 < 6") == "<b>Ventas</b> &amp; &lt;script&gt;x&lt;/script&gt; 5 &lt; 6"
    assert texto_plano("<b>a</b> <i>b</i>") == "a b"
    partes = trocear("\n".join(["línea"] * 2000), 4000)
    assert len(partes) > 1 and all(len(p) <= 4000 for p in partes)


def test_limite_uso():
    t = [0.0]
    lim = LimiteUso(30, reloj=lambda: t[0])
    assert all(lim.permitir("u") for _ in range(30))
    assert not lim.permitir("u")                      # C08: la 31.ª se rechaza
    assert lim.permitir("otro")
    t[0] = 3601
    assert lim.permitir("u")


def test_reloj():
    assert Reloj(AHORA).marca() == "[Ahora en La Habana: miércoles 30 de septiembre de 2026, 11:30]"


async def test_validacion_parametros_antes_de_la_bd():
    db = BaseDatos("host=/no-existe", Reloj(AHORA))                       # no se abre: no debe hacer falta
    r, traza = await db.herramienta("get_sales_summary", {"from": "2026-08-01", "to": "2026-08-31", "drop": 1})
    assert r["error_code"] == "invalid_params" and traza["status"] == "error"
    r, _ = await db.herramienta("borrar_todo", {})
    assert r["error_code"] == "invalid_params"


# Planificador de alertas -------------------------------------------------------------------------
def alerta(n, sku="GRA-010"):
    return {"alert_key": f"regla{n}:{sku}:2026-09-30", "rule": f"regla{n}", "priority": "urgent", "title": f"Alerta {n}",
            "detail": "detalle", "product": {"sku": sku, "name": "x"}}


class DbAlertas:
    def __init__(self, alertas):
        self.alertas = alertas

    async def herramienta(self, nombre, params):
        assert (nombre, params) == ("get_alerts", {"min_priority": "urgent"})
        return {"status": "ok", "data": {"alerts": self.alertas}}, {}


@pytest.fixture
def registro(tmp_path):
    return Registro(None, str(tmp_path / "registro.jsonl"))


async def test_planificador_limite_y_repeticion(registro, tmp_path):
    await registro.abrir()
    enviados = []

    async def enviar(t, b):
        enviados.append((t, b))

    reloj = Reloj(AHORA)
    p = Planificador(DbAlertas([alerta(i) for i in range(1, 5)]), registro, reloj, enviar)
    primera = await p.revisar_alertas()
    assert len(primera) == 3                                     # D09: máximo 3 al día
    assert "<b>Alerta 1</b>" in enviados[0][0] and enviados[0][1]["Ver producto"] == "producto:GRA-010"
    assert await p.revisar_alertas() == []                       # D08/D09: no repite y no pasa de 3
    reloj.ahora_fija = datetime(2026, 9, 30, 22, 15, tzinfo=HABANA)
    assert await p.revisar_alertas() == []                       # D10: silencio nocturno
    reloj.ahora_fija = datetime(2026, 10, 1, 8, 0, tzinfo=HABANA)
    p.db = DbAlertas([alerta(1, "ENE-004")])
    assert len(await p.revisar_alertas()) == 1                   # a las 8:00 se envía lo pendiente
    assert (tmp_path / "registro.jsonl").read_text().count('"alerta_enviada"') == 4


# Bot de Telegram: autorización -------------------------------------------------------------------
class Mensaje:
    def __init__(self, text="hola"):
        self.text, self.respuestas = text, []

    async def reply_text(self, t, **k):
        self.respuestas.append(t)


class Chat:
    def __init__(self, tipo="private"):
        self.type, self.id, self.salio = tipo, 1, False

    async def leave(self):
        self.salio = True


def update(user_id, tipo="private"):
    return NS(effective_user=NS(id=user_id), effective_chat=Chat(tipo), effective_message=Mensaje())


async def test_autorizacion_bot(registro):
    from agente_interno.bot_telegram import NO_AUTORIZADO, BotTelegram
    await registro.abrir()
    bot = BotTelegram("123456:TEST", 42, agente([])[0], registro, lambda enviar: None, limite_hora=2)
    assert await bot._autorizado(update(42))
    extraño = update(7)
    assert not await bot._autorizado(extraño) and extraño.effective_message.respuestas == [NO_AUTORIZADO]   # C06
    grupo = update(42, "group")
    assert not await bot._autorizado(grupo) and grupo.effective_chat.salio                                  # C07
    assert await bot._autorizado(update(42))
    limitado = update(42)
    assert not await bot._autorizado(limitado) and "límite" in limitado.effective_message.respuestas[0]     # C08
