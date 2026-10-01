"""Configuración leída de variables de entorno (02_arquitectura.md §2.5). Nunca se registran sus valores."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time


def _bool(v: str | None, defecto: bool = False) -> bool:
    if v is None or v == "":
        return defecto
    return v.strip().lower() in ("1", "true", "si", "sí", "yes", "on")


@dataclass(frozen=True)
class Config:
    db_url_agente: str
    telegram_token: str | None = None
    telegram_owner_id: int | None = None
    db_url_registro: str | None = None
    orquestador_token: str | None = None
    negocio_id: int | None = None
    modelo: str = "claude-opus-5-5"
    esfuerzo: str = "medium"
    fallbacks: bool = True
    # Modo demo: congela "ahora" (ISO 8601 con zona). Útil mientras no exista el alimentador diario.
    ahora_fija: datetime | None = None
    limite_consultas_hora: int = 30
    hora_resumen: time = time(19, 30)
    alertas_max_dia: int = 3
    alertas_desde: time = time(8, 0)
    alertas_hasta: time = time(21, 0)
    api_host: str = "127.0.0.1"
    api_port: int = 8080
    archivo_registro: str = "registro/registro.jsonl"

    @staticmethod
    def desde_entorno() -> "Config":
        def req(nombre: str) -> str:
            v = os.environ.get(nombre)
            if not v:
                raise RuntimeError(f"Falta la variable de entorno {nombre}")
            return v

        owner = os.environ.get("TELEGRAM_OWNER_ID")
        ahora = os.environ.get("AGENTE_AHORA_FIJA")
        hh, mm = (os.environ.get("HORA_RESUMEN") or "19:30").split(":")
        return Config(
            db_url_agente=req("DB_URL_AGENTE"),
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_owner_id=int(owner) if owner else None,
            db_url_registro=os.environ.get("DB_URL_REGISTRO") or None,
            orquestador_token=os.environ.get("ORQUESTADOR_TOKEN") or None,
            negocio_id=int(os.environ["NEGOCIO_ID"]) if os.environ.get("NEGOCIO_ID") else None,
            modelo=os.environ.get("MODELO_CLAUDE") or "claude-opus-5-5",
            esfuerzo=os.environ.get("ESFUERZO_CLAUDE") or "medium",
            fallbacks=_bool(os.environ.get("FALLBACKS_CLAUDE"), True),
            ahora_fija=datetime.fromisoformat(ahora) if ahora else None,
            limite_consultas_hora=int(os.environ.get("LIMITE_CONSULTAS_HORA") or 30),
            hora_resumen=time(int(hh), int(mm)),
            api_host=os.environ.get("API_HOST") or "127.0.0.1",
            api_port=int(os.environ.get("API_PORT") or 8080),
            archivo_registro=os.environ.get("ARCHIVO_REGISTRO") or "registro/registro.jsonl",
        )
