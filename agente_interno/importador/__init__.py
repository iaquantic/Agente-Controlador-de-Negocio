"""Importador de los datos de un negocio real (catálogo, ventas, compras, devoluciones, inventario y tasas).

    python -m agente_interno.importador plantillas datos/importar     # crea las plantillas para el cliente
    python -m agente_interno.importador validar datos/importar        # revisa los archivos sin tocar la base de datos
    python -m agente_interno.importador importar datos/importar       # reconstruye los datos del negocio

Detalle de los archivos y columnas en docs/IMPORTACION.md.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from .lectura import ZONA, ErrorDato, fecha_hora, leer_carpeta
from .motor import Carga, Constructor, Informe


def preparar(carpeta: Path, ahora: datetime | None = None, conn=None, eltoque: bool = False) -> tuple[Carga, Informe]:
    """Lee la carpeta y construye la carga. Con conexión, usa las tasas que ya están en la base de datos."""
    from .escritura import tasas_existentes

    ahora = ahora or datetime.now(ZONA)
    if not carpeta.is_dir():
        raise ValueError(f"No existe la carpeta {carpeta}")
    tablas, avisos = leer_carpeta(carpeta)
    tasas_bd = tasas_existentes(conn) if conn is not None else {}
    carga, informe = Constructor(tablas, ahora, tasas_bd, avisos).construir()
    if eltoque:
        from .tasas import descargar, dias_sin_tasa

        clave = os.environ.get("ELTOQUE_API_KEY")
        fechas = _fechas(tablas)
        if not clave:
            informe.avisos_archivo.append("Falta ELTOQUE_API_KEY: no se descargan tasas de elTOQUE.")
        elif fechas:
            conocidas = set(tasas_bd) | {d for d, (_, fuente) in carga.tasas.items() if fuente != "ventas"}
            faltan = dias_sin_tasa(min(fechas), ahora.astimezone(ZONA).date(), conocidas)
            if faltan:
                nuevas = descargar(faltan, clave)
                carga, informe = Constructor(tablas, ahora, tasas_bd, avisos, nuevas).construir()
                if len(nuevas) < len(faltan):
                    informe.avisos_archivo.append(f"elTOQUE no devolvió la tasa de {len(faltan) - len(nuevas)} día(s).")
    return carga, informe


def _fechas(tablas) -> list:
    """Días con ventas, compras o devoluciones en los archivos (incluidas las filas que aún no tienen tasa)."""
    salida = []
    for t in tablas:
        if t.tipo in ("ventas", "compras", "devoluciones"):
            for f in t.filas:
                try:
                    r = fecha_hora(f.get("fecha"))
                except ErrorDato:
                    continue
                if r:
                    salida.append(r[0].astimezone(ZONA).date())
    return salida
