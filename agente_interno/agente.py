"""Núcleo del Agente Interno: bucle de herramientas con Claude (09_system_prompt.md).

- El historial de cada conversación solo se amplía (nunca se recorta ni se edita): así los bloques de razonamiento
  siguen siendo válidos. Cuando la conversación se alarga o se enfría, se empieza una nueva.
- La fecha y hora van en cada mensaje, no en el system prompt, para que este se pueda cachear.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import anthropic

from .filtro import filtrar
from .herramientas import HERRAMIENTAS
from .tiempo import Reloj

log = logging.getLogger(__name__)

PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "agente_interno_system_prompt.md"
MAX_ITERACIONES = 10
MAX_TURNOS = 12                 # intercambios por conversación antes de empezar otra
INACTIVIDAD_S = 2 * 3600        # una conversación caduca tras 2 h sin mensajes
SIN_RESPUESTA = "Ahora mismo no puedo consultar los datos. Inténtalo en unos minutos."


class Ejecutor(Protocol):
    async def herramienta(self, nombre: str, params: dict | None) -> tuple[dict, dict]: ...


@dataclass
class Respuesta:
    texto: str
    herramientas: list[dict] = field(default_factory=list)
    tokens: dict = field(default_factory=dict)
    estado: str = "ok"                   # ok | error | rechazado | bloqueado
    error: str | None = None
    latencia_ms: int = 0


@dataclass
class _Conversacion:
    mensajes: list[dict] = field(default_factory=list)
    ultima: float = 0.0
    turnos: int = 0


def cargar_prompt(nombre_negocio: str, canal: str) -> str:
    return PROMPT.read_text(encoding="utf-8").replace("{{NOMBRE_NEGOCIO}}", nombre_negocio).replace("{{CANAL}}", canal)


def _texto(contenido: list[Any]) -> str:
    return "\n".join(b.text for b in contenido if getattr(b, "type", None) == "text").strip()


class AgenteInterno:
    def __init__(self, ejecutor: Ejecutor, reloj: Reloj, *, nombre_negocio: str = "MercadoAgentico",
                 modelo: str = "claude-opus-5-5", esfuerzo: str = "medium", fallbacks: bool = True,
                 cliente: Any | None = None):
        self.ejecutor = ejecutor
        self.reloj = reloj
        self.modelo = modelo
        self.esfuerzo = esfuerzo
        self.fallbacks = fallbacks
        self.cliente = cliente if cliente is not None else anthropic.AsyncAnthropic()
        self._sistemas = {c: cargar_prompt(nombre_negocio, c) for c in ("telegram", "orquestador")}
        self._conversaciones: dict[str, _Conversacion] = {}
        self._bloqueos: dict[str, asyncio.Lock] = {}

    def _conversacion(self, clave: str) -> _Conversacion:
        c = self._conversaciones.get(clave)
        if c is None or c.turnos >= MAX_TURNOS or time.monotonic() - c.ultima > INACTIVIDAD_S:
            c = self._conversaciones[clave] = _Conversacion()
        return c

    def olvidar(self, clave: str) -> None:
        self._conversaciones.pop(clave, None)

    async def _llamar(self, sistema: str, mensajes: list[dict]):
        kwargs: dict[str, Any] = dict(
            model=self.modelo,
            max_tokens=16000,
            system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
            tools=HERRAMIENTAS,
            messages=mensajes,
            output_config={"effort": self.esfuerzo},
        )
        if self.fallbacks:
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        return await self.cliente.beta.messages.create(**kwargs)

    async def responder(self, clave: str, texto: str, canal: str = "telegram", *, conservar: bool = True) -> Respuesta:
        """Responde a un mensaje. `clave` identifica la conversación (chat de Telegram, petición, etc.)."""
        bloqueo = self._bloqueos.setdefault(clave, asyncio.Lock())
        async with bloqueo:
            return await self._responder(clave, texto, canal, conservar)

    async def _responder(self, clave: str, texto: str, canal: str, conservar: bool) -> Respuesta:
        inicio = time.monotonic()
        conv = self._conversacion(clave) if conservar else _Conversacion()
        mensajes = conv.mensajes
        mensajes.append({"role": "user", "content": f"{self.reloj.marca()}\n{texto}"})
        resp = Respuesta(texto="")
        tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        try:
            for _ in range(MAX_ITERACIONES):
                r = await self._llamar(self._sistemas[canal], mensajes)
                u = r.usage
                tokens["input"] += u.input_tokens or 0
                tokens["output"] += u.output_tokens or 0
                tokens["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
                tokens["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
                mensajes.append({"role": "assistant", "content": r.content})

                if r.stop_reason == "refusal":
                    resp.texto, resp.estado = SIN_RESPUESTA, "rechazado"
                    break
                if r.stop_reason == "pause_turn":
                    continue
                if r.stop_reason == "tool_use":
                    llamadas = [b for b in r.content if getattr(b, "type", None) == "tool_use"]
                    resultados = await asyncio.gather(*(self.ejecutor.herramienta(b.name, b.input) for b in llamadas))
                    bloques = []
                    for b, (res, traza) in zip(llamadas, resultados):
                        resp.herramientas.append(traza)
                        bloques.append({"type": "tool_result", "tool_use_id": b.id,
                                        "content": json.dumps(res, ensure_ascii=False, default=str),
                                        "is_error": res.get("status") == "error"})
                    mensajes.append({"role": "user", "content": bloques})
                    continue
                resp.texto = _texto(r.content) or SIN_RESPUESTA     # end_turn, max_tokens, stop_sequence
                break
            else:
                resp.texto, resp.estado, resp.error = SIN_RESPUESTA, "error", "demasiadas iteraciones"
        except anthropic.APIError as e:
            log.exception("Error de la API de Claude")
            resp.texto, resp.estado, resp.error = SIN_RESPUESTA, "error", f"{type(e).__name__}"
        else:
            conv.turnos += 1
            conv.ultima = time.monotonic()
        if resp.estado != "ok" and conservar:
            self.olvidar(clave)              # no dejar un historial a medias (dos turnos de usuario seguidos)

        if canal == "telegram":
            resp.texto, bloqueado = filtrar(resp.texto)
            if bloqueado:
                resp.estado, resp.error = "bloqueado", "filtro de salida"
        resp.tokens = tokens
        resp.latencia_ms = int((time.monotonic() - inicio) * 1000)
        return resp
