"""Filtro de salida (06 §6.5) y saneado del HTML de Telegram."""
from __future__ import annotations

import html
import re

from .herramientas import NOMBRES

RESPUESTA_NEUTRA = "Ahora mismo no puedo darte esa información. Pregúntame de otra forma o inténtalo en unos minutos."

_TABLAS = ("lineas_venta", "lineas_compra", "movimientos_inventario", "precios_producto", "tasas_cambio",
           "config_categoria", "devoluciones_pendientes", "alertas_enviadas", "accesos_denegados")
_PATRONES = [
    re.compile(r"\b(select|insert|update|delete|drop|alter|create)\b[\s\S]{0,200}?\b(from|into|table|set|function)\b", re.I),
    re.compile(r"\b(public|agente|registro|simulador|extensions)\.[a-z_]+", re.I),
    re.compile(r"postgres(ql)?://", re.I),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]+"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),            # token de bot de Telegram
    re.compile(r"\b(" + "|".join(sorted(NOMBRES | set(_TABLAS))) + r")\b"),
    re.compile(r"\b(sqlstate|traceback|psycopg|stack trace)\b", re.I),
    re.compile(r"<(limites_absolutos|uso_de_herramientas|estilo_telegram|situaciones_especiales|mision)>", re.I),
]


def es_seguro(texto: str) -> bool:
    return not any(p.search(texto or "") for p in _PATRONES)


def filtrar(texto: str) -> tuple[str, bool]:
    """Devuelve (texto a enviar, bloqueado)."""
    if es_seguro(texto):
        return texto, False
    return RESPUESTA_NEUTRA, True


_ETIQUETA = re.compile(r"&lt;(/?)(b|i)&gt;")


def html_telegram(texto: str) -> str:
    """Escapa todo y vuelve a permitir solo <b> e <i>."""
    return _ETIQUETA.sub(r"<\1\2>", html.escape(texto or "", quote=False))


def texto_plano(texto: str) -> str:
    return re.sub(r"</?(b|i)>", "", texto or "")


def trocear(texto: str, limite: int = 4000) -> list[str]:
    """Telegram admite 4096 caracteres por mensaje: corta por párrafos."""
    if len(texto) <= limite:
        return [texto]
    partes, actual = [], ""
    for parrafo in texto.split("\n"):
        if len(actual) + len(parrafo) + 1 > limite and actual:
            partes.append(actual)
            actual = ""
        actual = f"{actual}\n{parrafo}" if actual else parrafo
    if actual:
        partes.append(actual)
    return partes
