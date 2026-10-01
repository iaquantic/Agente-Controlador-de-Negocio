"""Acceso de solo lectura a las 12 herramientas del esquema `agente`.

El modelo nunca escribe SQL: elige herramienta y parámetros, que se validan aquí y otra vez en la base de datos.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from jsonschema import Draft202012Validator
from psycopg import errors, sql
from psycopg_pool import AsyncConnectionPool

from .herramientas import ESQUEMAS, NOMBRES
from .tiempo import Reloj

log = logging.getLogger(__name__)


def _error(herramienta: str, codigo: str, mensaje: str) -> dict:
    return {"status": "error", "tool": herramienta, "error_code": codigo, "message": mensaje}


def _filas(resultado: dict) -> int | None:
    datos = resultado.get("data")
    if not isinstance(datos, dict):
        return None
    for clave in ("items", "matches", "alerts", "series", "groups"):
        if isinstance(datos.get(clave), list):
            return len(datos[clave])
    return 1


class BaseDatos:
    def __init__(self, url: str, reloj: Reloj, negocio_id: int | None = None, max_size: int = 4):
        self.reloj = reloj
        self.negocio_id = negocio_id
        self.pool = AsyncConnectionPool(url, min_size=1, max_size=max_size, open=False, timeout=15,
                                        kwargs={"autocommit": False, "prepare_threshold": None})
        self._validadores = {n: Draft202012Validator(ESQUEMAS[n]) for n in NOMBRES}

    async def abrir(self) -> None:
        await self.pool.open(wait=True)

    async def cerrar(self) -> None:
        await self.pool.close()

    async def herramienta(self, nombre: str, params: dict[str, Any] | None) -> tuple[dict, dict]:
        """Ejecuta una herramienta. Devuelve (resultado, traza para el registro)."""
        params = params or {}
        inicio = time.monotonic()
        if nombre not in NOMBRES:
            res = _error(nombre, "invalid_params", "Herramienta desconocida.")
        else:
            fallos = sorted(self._validadores[nombre].iter_errors(params), key=lambda e: e.path)
            if fallos:
                res = _error(nombre, "invalid_params", f"Parámetros no válidos: {fallos[0].message}")
            else:
                res = await self._ejecutar(nombre, params)
        traza = {"name": nombre, "params": params, "status": res.get("status"), "rows": _filas(res),
                 "ms": int((time.monotonic() - inicio) * 1000)}
        return res, traza

    async def _ejecutar(self, nombre: str, params: dict) -> dict:
        consulta = sql.SQL("select agente.{}(%s::jsonb)").format(sql.Identifier(nombre))
        try:
            async with self.pool.connection() as conn:
                async with conn.transaction():
                    if self.reloj.ahora_fija is not None:
                        await conn.execute("select set_config('agente.ahora', %s, true)", (self.reloj.ahora().isoformat(),))
                    if self.negocio_id is not None:
                        await conn.execute("select set_config('agente.negocio_id', %s, true)", (str(self.negocio_id),))
                    cur = await conn.execute(consulta, (json.dumps(params, ensure_ascii=False),))
                    fila = await cur.fetchone()
            return fila[0]
        except errors.QueryCanceled:
            return _error(nombre, "timeout", "La consulta tardó demasiado.")
        except Exception:  # el detalle va al log del servidor, nunca al modelo ni al dueño
            log.exception("Fallo ejecutando la herramienta %s", nombre)
            return _error(nombre, "internal", "No se pudo completar la consulta.")
