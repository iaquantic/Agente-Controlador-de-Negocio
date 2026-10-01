"""Arranque: `python -m agente_interno` (bot de Telegram + API del orquestador + tareas programadas)."""
from __future__ import annotations

import asyncio
import logging
import os

import uvicorn
from dotenv import load_dotenv

from .agente import AgenteInterno
from .bot_telegram import BotTelegram
from .config import Config
from .db import BaseDatos
from .orquestador import crear_app
from .planificador import Planificador
from .registro import Registro
from .tiempo import Reloj


async def principal() -> None:
    load_dotenv()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)      # no registrar URLs con el token del bot
    cfg = Config.desde_entorno()
    reloj = Reloj(cfg.ahora_fija)
    if cfg.ahora_fija:
        logging.warning("MODO DEMO: la hora está congelada en %s", reloj.ahora().isoformat())

    db = BaseDatos(cfg.db_url_agente, reloj, cfg.negocio_id)
    registro = Registro(cfg.db_url_registro, cfg.archivo_registro)
    await db.abrir()
    await registro.abrir()
    agente = AgenteInterno(db, reloj, modelo=cfg.modelo, esfuerzo=cfg.esfuerzo, fallbacks=cfg.fallbacks)

    tareas = []
    bot = None
    if cfg.telegram_token and cfg.telegram_owner_id:
        bot = BotTelegram(cfg.telegram_token, cfg.telegram_owner_id, agente, registro,
                          lambda enviar: Planificador(db, registro, reloj, enviar, max_dia=cfg.alertas_max_dia,
                                                      desde=cfg.alertas_desde, hasta=cfg.alertas_hasta),
                          limite_hora=cfg.limite_consultas_hora, hora_resumen=cfg.hora_resumen)
        bot.programar()
        await bot.app.initialize()
        await bot.app.start()
        await bot.app.updater.start_polling(drop_pending_updates=True)
        logging.info("Bot de Telegram en marcha")
    else:
        logging.warning("Sin TELEGRAM_BOT_TOKEN/TELEGRAM_OWNER_ID: el bot no se inicia")

    if cfg.orquestador_token:
        app = crear_app(db, agente, registro, reloj, cfg.orquestador_token)
        servidor = uvicorn.Server(uvicorn.Config(app, host=cfg.api_host, port=cfg.api_port, log_level="warning"))
        tareas.append(asyncio.create_task(servidor.serve()))
        logging.info("API del orquestador en http://%s:%s/v1/consulta", cfg.api_host, cfg.api_port)

    try:
        await asyncio.Event().wait()
    finally:
        if bot:
            await bot.app.updater.stop()
            await bot.app.stop()
            await bot.app.shutdown()
        for t in tareas:
            t.cancel()
        await db.cerrar()
        await registro.cerrar()


if __name__ == "__main__":
    try:
        asyncio.run(principal())
    except KeyboardInterrupt:
        pass
