"""Fecha y hora de La Habana (real o congelada en modo demo)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

HABANA = ZoneInfo("America/Havana")
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
          "octubre", "noviembre", "diciembre"]


class Reloj:
    def __init__(self, ahora_fija: datetime | None = None):
        self.ahora_fija = ahora_fija

    def ahora(self) -> datetime:
        if self.ahora_fija is not None:
            return self.ahora_fija.astimezone(HABANA)
        return datetime.now(HABANA)

    def marca(self) -> str:
        """Texto que se antepone a cada mensaje del dueño."""
        a = self.ahora()
        return f"[Ahora en La Habana: {_DIAS[a.weekday()]} {a.day} de {_MESES[a.month - 1]} de {a.year}, {a:%H:%M}]"
