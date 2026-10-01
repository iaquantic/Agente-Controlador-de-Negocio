"""Bot de Telegram (07_contrato_telegram.md)."""
from __future__ import annotations

import logging
from datetime import time as dtime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ChatType, ParseMode
from telegram.error import BadRequest
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters)

from .agente import AgenteInterno
from .filtro import html_telegram, texto_plano, trocear
from .planificador import PREGUNTA_RESUMEN, Planificador
from .registro import LimiteUso, Registro
from .tiempo import HABANA

log = logging.getLogger(__name__)

NO_AUTORIZADO = "Este asistente es privado. No estás autorizado."
LIMITE = "Has llegado al límite de consultas por hora. Vuelve a intentarlo en unos minutos."
BIENVENIDA = ("👋 Hola, soy tu asistente del negocio. Puedo decirte cómo van las ventas, qué se está agotando, qué no se "
              "vende, dónde pierdes margen y si hay algo raro.\n\nEscríbeme con tus palabras o usa /ayuda.")
AYUDA = ("<b>Qué puedes preguntarme</b>\n"
         "• ¿Cuánto vendí hoy?\n• ¿Qué producto estoy vendiendo más?\n• ¿Qué tengo que reponer esta semana?\n"
         "• ¿Qué productos me dejan poco margen?\n• ¿Hay algo raro que deba saber?\n\n"
         "<b>Comandos</b>\n/resumen · /ventas · /stock · /producto &lt;nombre&gt; · /alertas · /ayuda\n\n"
         "<i>Solo consulto y analizo: no cambio precios, stock ni ventas.</i>")

# Consultas predefinidas de comandos y botones (callback_data → pregunta al agente). Nunca ejecutan acciones.
CONSULTAS = {
    "resumen": "Dame el resumen de cómo va el negocio hoy.",
    "alertas": "¿Qué alertas hay activas? Empieza por las urgentes.",
    "alertas_urgentes": "¿Qué alertas urgentes hay ahora?",
    "stock": "¿Qué productos están agotados, en riesgo de quedarse sin stock o con stock bajo? Prioritarios primero.",
    "excesos": "¿Qué productos tienen exceso de stock y cuánto dinero tengo inmovilizado?",
    "sin_movimiento": "¿Qué productos tienen stock pero no se venden?",
    "ventas_hoy": "¿Cuánto vendí hoy?",
    "ventas_semana": "¿Cuánto llevo vendido esta semana y cómo va frente a la semana pasada?",
    "ventas_mes": "¿Cuánto llevo vendido este mes y cómo va frente al mes pasado?",
    "ventas_mes_pasado": "¿Cuánto vendí el mes pasado?",
}
BOTONES = {
    "resumen": {"Ver alertas": "alertas", "Stock": "stock", "Esta semana": "ventas_semana"},
    "alertas": {"Urgentes": "alertas_urgentes", "Stock": "stock"},
    "stock": {"Excesos": "excesos", "Sin movimiento": "sin_movimiento"},
    "ventas": {"Hoy": "ventas_hoy", "Semana": "ventas_semana", "Mes": "ventas_mes", "Mes pasado": "ventas_mes_pasado"},
    "inicio": {"Resumen": "resumen", "Alertas": "alertas"},
}


def teclado(botones: dict[str, str] | None) -> InlineKeyboardMarkup | None:
    if not botones:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in botones.items()]])


class BotTelegram:
    def __init__(self, token: str, owner_id: int, agente: AgenteInterno, registro: Registro, planificador_factory,
                 *, limite_hora: int = 30, hora_resumen: dtime = dtime(19, 30)):
        self.owner_id = owner_id
        self.agente = agente
        self.registro = registro
        self.limite = LimiteUso(limite_hora)
        self.hora_resumen = hora_resumen
        self.app = Application.builder().token(token).build()
        self.planificador: Planificador = planificador_factory(self.enviar_al_dueno)
        self._registrar_handlers()

    # Autorización ---------------------------------------------------------------------------
    async def _autorizado(self, update: Update) -> bool:
        usuario, chat = update.effective_user, update.effective_chat
        if chat and chat.type != ChatType.PRIVATE:
            await self.registro.acceso_denegado(usuario.id if usuario else None, chat.type, None)
            try:
                await chat.leave()
            except Exception:
                pass
            return False
        if not usuario or usuario.id != self.owner_id:
            texto = update.effective_message.text if update.effective_message else None
            await self.registro.acceso_denegado(usuario.id if usuario else None, chat.type if chat else None, texto)
            if update.effective_message:
                await update.effective_message.reply_text(NO_AUTORIZADO)
            return False
        if not self.limite.permitir(usuario.id):
            await self.registro.interaccion(canal="telegram", usuario_id=usuario.id, autorizado=True, entrada=None,
                                            herramientas=[], latencia_ms=None, tokens=None, respuesta=LIMITE, estado="limite")
            await update.effective_message.reply_text(LIMITE)
            return False
        return True

    # Envío -------------------------------------------------------------------------------------
    async def _enviar(self, chat_id: int, texto_html: str, botones: dict | None = None) -> None:
        partes = trocear(texto_html)
        for i, parte in enumerate(partes):
            markup = teclado(botones) if i == len(partes) - 1 else None
            try:
                await self.app.bot.send_message(chat_id, parte, parse_mode=ParseMode.HTML, reply_markup=markup)
            except BadRequest:
                await self.app.bot.send_message(chat_id, texto_plano(parte), reply_markup=markup)

    async def enviar_al_dueno(self, texto_html: str, botones: dict | None = None) -> None:
        await self._enviar(self.owner_id, texto_html, botones)

    async def _consultar(self, update: Update, pregunta: str, botones: dict | None = None, *, entrada: str | None = None):
        chat_id = update.effective_chat.id
        await self.app.bot.send_chat_action(chat_id, ChatAction.TYPING)
        r = await self.agente.responder(f"tg:{chat_id}", pregunta, canal="telegram")
        await self._enviar(chat_id, html_telegram(r.texto), botones)
        await self.registro.interaccion(canal="telegram", usuario_id=update.effective_user.id, autorizado=True,
                                        entrada=entrada or pregunta, herramientas=r.herramientas, latencia_ms=r.latencia_ms,
                                        tokens=r.tokens, respuesta=r.texto, estado=r.estado, error=r.error)
        if not r.herramientas and "❔" in r.texto:
            await self.registro.pregunta_sin_herramienta(entrada or pregunta)

    # Handlers ----------------------------------------------------------------------------------
    def _registrar_handlers(self) -> None:
        a = self.app
        a.add_handler(CommandHandler("start", self.cmd_start))
        a.add_handler(CommandHandler("ayuda", self.cmd_ayuda))
        a.add_handler(CommandHandler("help", self.cmd_ayuda))
        a.add_handler(CommandHandler("resumen", self.cmd_resumen))
        a.add_handler(CommandHandler("ventas", self.cmd_ventas))
        a.add_handler(CommandHandler("stock", self.cmd_stock))
        a.add_handler(CommandHandler("producto", self.cmd_producto))
        a.add_handler(CommandHandler("alertas", self.cmd_alertas))
        a.add_handler(CallbackQueryHandler(self.boton))
        a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.texto))
        a.add_handler(MessageHandler(filters.ChatType.GROUPS, self._grupo))

    async def _grupo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._autorizado(update)

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._autorizado(update):
            await update.effective_message.reply_text(BIENVENIDA, reply_markup=teclado(BOTONES["inicio"]))

    async def cmd_ayuda(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._autorizado(update):
            await update.effective_message.reply_text(AYUDA, parse_mode=ParseMode.HTML)

    async def cmd_resumen(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._autorizado(update):
            await self._consultar(update, CONSULTAS["resumen"], BOTONES["resumen"], entrada="/resumen")

    async def cmd_ventas(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._autorizado(update):
            await update.effective_message.reply_text("📈 ¿De qué periodo?", reply_markup=teclado(BOTONES["ventas"]))

    async def cmd_stock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._autorizado(update):
            await self._consultar(update, CONSULTAS["stock"], BOTONES["stock"], entrada="/stock")

    async def cmd_alertas(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._autorizado(update):
            await self._consultar(update, CONSULTAS["alertas"] + " Muestra como máximo 8 y di cuántas más hay.",
                                  BOTONES["alertas"], entrada="/alertas")

    async def cmd_producto(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._autorizado(update):
            return
        nombre = " ".join(context.args or []).strip()
        if not nombre:
            await update.effective_message.reply_text("¿Qué producto quieres ver? Escribe por ejemplo: /producto aceite")
            return
        await self._consultar(update, f"Dame la ficha del producto: {nombre[:60]}", entrada=f"/producto {nombre[:60]}")

    async def boton(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        await q.answer()
        if not await self._autorizado(update):
            return
        dato = q.data or ""
        if dato.startswith("producto:"):
            await self._consultar(update, f"Dame la ficha del producto con código {dato.split(':', 1)[1][:20]}.",
                                  entrada=f"[botón] {dato}")
        elif dato in CONSULTAS:
            botones = BOTONES.get("alertas" if dato.startswith("alertas") else "stock" if dato in ("excesos", "sin_movimiento") else "")
            await self._consultar(update, CONSULTAS[dato], botones, entrada=f"[botón] {dato}")

    async def texto(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._autorizado(update):
            await self._consultar(update, update.effective_message.text[:2000])

    # Tareas programadas ------------------------------------------------------------------------
    async def _job_resumen(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        r = await self.agente.responder("planificador:resumen", PREGUNTA_RESUMEN, canal="telegram", conservar=False)
        await self.enviar_al_dueno(html_telegram(r.texto), BOTONES["resumen"])
        await self.registro.interaccion(canal="planificador", usuario_id=self.owner_id, autorizado=True,
                                        entrada="resumen diario", herramientas=r.herramientas, latencia_ms=r.latencia_ms,
                                        tokens=r.tokens, respuesta=r.texto, estado=r.estado, error=r.error)

    async def _job_alertas(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        enviadas = await self.planificador.revisar_alertas()
        if enviadas:
            await self.registro.interaccion(canal="planificador", usuario_id=self.owner_id, autorizado=True,
                                            entrada="revisión de alertas", herramientas=[{"name": "get_alerts"}],
                                            latencia_ms=None, tokens=None,
                                            respuesta="; ".join(a["title"] for a in enviadas), estado="ok")

    async def _job_purga(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.registro.purgar()

    def programar(self) -> None:
        jq = self.app.job_queue
        jq.run_daily(self._job_resumen, time=self.hora_resumen.replace(tzinfo=HABANA), name="resumen")
        jq.run_repeating(self._job_alertas, interval=1800, first=60, name="alertas")
        jq.run_daily(self._job_purga, time=dtime(3, 0, tzinfo=HABANA), name="purga")
