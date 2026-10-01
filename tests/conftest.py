"""Configuración común de las pruebas.

Las pruebas de base de datos necesitan un PostgreSQL con el esquema y los datos de demostración
(ver tests/README.md). Se conectan como `agente_lectura` para probar exactamente los permisos reales.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import psycopg
import pytest

# Hora congelada: los datos de demostración terminan el 30/9/2026 a las 11:30 (La Habana).
AHORA = "2026-09-30T11:30:00-04:00"
URL_ADMIN = os.environ.get("TEST_DB_URL_ADMIN", "host=/var/tmp/pgtest port=55432 user=postgres dbname=mvp")
URL_AGENTE = os.environ.get("TEST_DB_URL_AGENTE", "host=/var/tmp/pgtest port=55432 user=agente_lectura dbname=mvp")


def _conectar(url: str):
    try:
        return psycopg.connect(url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as e:
        pytest.skip(f"Base de datos de pruebas no disponible: {e}")


@pytest.fixture(scope="session")
def admin():
    with _conectar(URL_ADMIN) as c:
        yield c


@pytest.fixture(scope="session")
def lectura():
    with _conectar(URL_AGENTE) as c:
        c.execute("select set_config('agente.ahora', %s, false)", (AHORA,))
        yield c


@pytest.fixture(scope="session")
def tool(lectura):
    """Llama a una herramienta como agente_lectura y devuelve el JSON."""
    def llamar(nombre: str, params: dict | None = None) -> dict:
        return lectura.execute(f"select agente.{nombre}(%s::jsonb)", (json.dumps(params or {}),)).fetchone()[0]
    return llamar


@pytest.fixture(scope="session")
def sql(admin):
    """Consulta independiente como administrador (para comprobar cifras por otro camino)."""
    def consultar(q: str, params: tuple = ()):
        return admin.execute(q, params).fetchall()
    return consultar


@pytest.fixture
def ahora():
    return datetime.fromisoformat(AHORA)
