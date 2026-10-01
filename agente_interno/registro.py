"""Registro de auditoría (06 §6.7). Usa el esquema `registro` si hay DB_URL_REGISTRO; si no, un archivo JSONL local."""
from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)


class Registro:
    def __init__(self, url: str | None, archivo: str):
        self.pool = AsyncConnectionPool(url, min_size=1, max_size=2, open=False, kwargs={"prepare_threshold": None}) if url else None
        self.archivo = archivo
        self._alertas: dict[str, datetime] = {}        # respaldo en memoria si no hay BD

    async def abrir(self) -> None:
        if self.pool:
            await self.pool.open(wait=True)
        else:
            os.makedirs(os.path.dirname(self.archivo) or ".", exist_ok=True)

    async def cerrar(self) -> None:
        if self.pool:
            await self.pool.close()

    def _archivo(self, tipo: str, datos: dict) -> None:
        with open(self.archivo, "a", encoding="utf-8") as f:
            f.write(json.dumps({"tipo": tipo, "fecha_hora": datetime.now(timezone.utc).isoformat(), **datos},
                               ensure_ascii=False, default=str) + "\n")

    async def _sql(self, consulta: str, params: tuple) -> list[tuple] | None:
        try:
            async with self.pool.connection() as conn:
                cur = await conn.execute(consulta, params)
                return await cur.fetchall() if cur.description else None
        except Exception:
            log.exception("No se pudo escribir en el registro")
            return None

    async def interaccion(self, *, canal: str, usuario_id: Any, autorizado: bool, entrada: str | None,
                          herramientas: list[dict], latencia_ms: int | None, tokens: dict | None,
                          respuesta: str | None, estado: str, error: str | None = None) -> None:
        datos = dict(canal=canal, usuario_id=str(usuario_id) if usuario_id is not None else None, autorizado=autorizado,
                     entrada=entrada, herramientas=herramientas, latencia_ms=latencia_ms, tokens=tokens,
                     respuesta=respuesta, estado=estado, error=error)
        if not self.pool:
            self._archivo("interaccion", datos)
            return
        await self._sql(
            "insert into registro.interacciones (canal, usuario_id, autorizado, entrada, herramientas, latencia_ms, tokens,"
            " respuesta, estado, error) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (canal, datos["usuario_id"], autorizado, entrada, Jsonb(herramientas), latencia_ms,
             Jsonb(tokens) if tokens else None, respuesta, estado, error))

    async def acceso_denegado(self, telegram_user_id: Any, chat_type: str | None, texto: str | None) -> None:
        texto = (texto or "")[:200]
        if not self.pool:
            self._archivo("acceso_denegado", dict(telegram_user_id=str(telegram_user_id), chat_type=chat_type, texto=texto))
            return
        await self._sql("insert into registro.accesos_denegados (telegram_user_id, chat_type, texto) values (%s, %s, %s)",
                        (str(telegram_user_id), chat_type, texto))

    async def pregunta_sin_herramienta(self, pregunta: str) -> None:
        if not self.pool:
            self._archivo("pregunta_sin_herramienta", dict(pregunta=pregunta))
            return
        await self._sql("insert into registro.preguntas_sin_herramienta (pregunta) values (%s)", (pregunta,))

    # Alertas: anti-repetición 24 h y máximo diario ---------------------------------------
    async def alertas_recientes(self, ahora: datetime) -> set[str]:
        desde = ahora - timedelta(hours=24)
        if not self.pool:
            return {k for k, f in self._alertas.items() if f > desde}
        filas = await self._sql("select alert_key from registro.alertas_enviadas where fecha_envio > %s", (desde,))
        return {f[0] for f in filas or []}

    async def alertas_enviadas_hoy(self, inicio_dia: datetime) -> int:
        if not self.pool:
            return sum(1 for f in self._alertas.values() if f >= inicio_dia)
        filas = await self._sql("select count(*) from registro.alertas_enviadas where fecha_envio >= %s", (inicio_dia,))
        return filas[0][0] if filas else 0

    async def alerta_enviada(self, alerta: dict, ahora: datetime) -> None:
        self._alertas[alerta["alert_key"]] = ahora
        if not self.pool:
            self._archivo("alerta_enviada", dict(alert_key=alerta["alert_key"], regla=alerta["rule"], prioridad=alerta["priority"]))
            return
        await self._sql(
            "insert into registro.alertas_enviadas (alert_key, regla, prioridad, fecha_deteccion, fecha_envio)"
            " values (%s, %s, %s, %s, %s) on conflict do nothing",
            (alerta["alert_key"], alerta["rule"], alerta["priority"], ahora, ahora))

    async def purgar(self, dias: int = 90) -> None:
        """Retención: borra los registros de más de `dias` días (06 §6.7)."""
        if not self.pool:
            return
        limite = datetime.now(timezone.utc) - timedelta(days=dias)
        for tabla, columna in (("interacciones", "fecha_hora"), ("alertas_enviadas", "fecha_deteccion"),
                               ("accesos_denegados", "fecha_hora"), ("preguntas_sin_herramienta", "fecha_hora")):
            await self._sql(f"delete from registro.{tabla} where {columna} < %s", (limite,))


class LimiteUso:
    """Máximo de consultas por usuario en una ventana deslizante de 1 hora."""

    def __init__(self, maximo: int, ventana_s: int = 3600, reloj=time.monotonic):
        self.maximo, self.ventana_s, self.reloj = maximo, ventana_s, reloj
        self._usos: dict[Any, deque] = defaultdict(deque)

    def permitir(self, usuario: Any) -> bool:
        ahora = self.reloj()
        usos = self._usos[usuario]
        while usos and ahora - usos[0] >= self.ventana_s:
            usos.popleft()
        if len(usos) >= self.maximo:
            return False
        usos.append(ahora)
        return True
