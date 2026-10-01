"""Mensajes proactivos: alertas urgentes y resumen diario (05 §5.7, 07 §7.6).

Las alertas las detecta la base de datos (`get_alerts`), nunca el modelo; el texto se compone con una plantilla
para que llegue siempre igual y al instante.
"""
from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Awaitable, Callable

from .filtro import html_telegram
from .registro import Registro
from .tiempo import Reloj

log = logging.getLogger(__name__)

PREGUNTA_RESUMEN = (
    "Genera el resumen diario del cierre (son las 19:30). Incluye: ventas de hoy frente a lo normal para este día, "
    "cómo va el mes, y lo más importante que debo atender (alertas urgentes y altas primero; luego, en una línea "
    "cada uno, excesos, mercancía parada, márgenes bajos y devoluciones si los hay). Máximo 10 líneas."
)


def texto_alerta(alerta: dict, hora: str) -> str:
    return (f"⚠️ <b>{html_telegram(alerta['title'])}</b>\n{html_telegram(alerta.get('detail') or '')}\n"
            f"<i>Detectado a las {hora}</i>")


class Planificador:
    def __init__(self, db, registro: Registro, reloj: Reloj, enviar: Callable[[str, dict | None], Awaitable[None]],
                 *, max_dia: int = 3, desde: time = time(8, 0), hasta: time = time(21, 0)):
        self.db, self.registro, self.reloj, self.enviar = db, registro, reloj, enviar
        self.max_dia, self.desde, self.hasta = max_dia, desde, hasta

    async def revisar_alertas(self) -> list[dict]:
        """Envía las alertas urgentes nuevas. Devuelve las enviadas."""
        ahora = self.reloj.ahora()
        if not (self.desde <= ahora.time() < self.hasta):
            return []                      # silencio nocturno: lo que siga activo se envía en la revisión de las 8:00
        res, _ = await self.db.herramienta("get_alerts", {"min_priority": "urgent"})
        if res.get("status") != "ok":
            log.warning("No se pudieron revisar las alertas: %s", res.get("error_code"))
            return []
        recientes = await self.registro.alertas_recientes(ahora)
        inicio_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        hueco = self.max_dia - await self.registro.alertas_enviadas_hoy(inicio_dia)
        enviadas = []
        for alerta in res["data"]["alerts"]:
            if hueco <= 0:
                break                       # el resto aparecerá en el resumen de las 19:30
            if alerta["alert_key"] in recientes:
                continue
            botones = {"Ver producto": f"producto:{alerta['product']['sku']}"} if alerta.get("product") else {}
            botones["Alertas"] = "alertas"
            await self.enviar(texto_alerta(alerta, ahora.strftime("%H:%M")), botones)
            await self.registro.alerta_enviada(alerta, ahora)
            enviadas.append(alerta)
            hueco -= 1
        return enviadas
