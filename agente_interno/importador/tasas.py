"""Descarga de la tasa USD→CUP de elTOQUE para los días que faltan (requiere ELTOQUE_API_KEY)."""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from decimal import Decimal

API = "https://tasas.eltoque.com/v1/trmi"
log = logging.getLogger(__name__)


def tasa_del_dia(dia: date, clave: str, timeout: float = 30) -> Decimal | None:
    """Tasa de primera hora (hasta las 08:00 de La Habana), como en el resto del sistema."""
    params = urllib.parse.urlencode({"date_from": f"{dia} 00:00:01", "date_to": f"{dia} 08:00:00"})
    req = urllib.request.Request(f"{API}?{params}", headers={"Authorization": f"Bearer {clave}"})
    for intento in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                usd = (json.load(r).get("tasas") or {}).get("USD")
            return Decimal(str(usd)) if usd else None
        except Exception as e:  # red o límite de peticiones: reintento con espera creciente
            if intento == 3:
                log.warning("No se pudo obtener la tasa del %s: %s", dia, e)
                return None
            time.sleep(2 ** (intento + 1))
    return None


def descargar(dias_que_faltan: list[date], clave: str, pausa: float = 0.3) -> dict[date, Decimal]:
    salida = {}
    for d in dias_que_faltan:
        v = tasa_del_dia(d, clave)
        if v:
            salida[d] = v
        time.sleep(pausa)
    return salida


def dias_sin_tasa(desde: date, hasta: date, conocidas: set[date]) -> list[date]:
    salida, d = [], desde
    while d <= hasta:
        if d not in conocidas:
            salida.append(d)
        d += timedelta(days=1)
    return salida
