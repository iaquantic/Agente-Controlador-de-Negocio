"""Línea de comandos del importador. Ver `python -m agente_interno.importador --help` y docs/IMPORTACION.md."""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from . import preparar
from .lectura import ZONA

PLANTILLAS = Path(__file__).parent / "plantillas"
MIGRACIONES = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
# Migración → consulta que dice si ya está aplicada.
APLICADA = {
    "20260930000000_esquema_inicial.sql": "select to_regclass('public.ventas') is not null",
    "20260930100000_esquema_agente.sql": "select to_regclass('agente.parametros') is not null",
    "20260930100100_herramientas_agente.sql": "select to_regprocedure('agente.get_data_quality(jsonb)') is not null",
    "20260930100200_roles_y_registro.sql": "select to_regclass('registro.interacciones') is not null",
    # Los roles son de todo el servidor, pero los permisos son de cada base de datos.
    "20261005000000_importador.sql": "select case when exists (select 1 from pg_roles where rolname = 'agente_importador') "
                                     "then has_table_privilege('agente_importador', 'public.ventas', 'INSERT') else false end",
}


def _conectar(url: str | None, variable: str):
    import psycopg

    if not url:
        raise SystemExit(f"Falta la cadena de conexión: define {variable} o usa --db.")
    return psycopg.connect(url, autocommit=True, connect_timeout=15)


def _ahora(texto: str | None) -> datetime:
    if not texto:
        return datetime.now(ZONA)
    dt = datetime.fromisoformat(texto)
    return dt if dt.tzinfo else dt.replace(tzinfo=ZONA)


def cmd_plantillas(args) -> int:
    destino = Path(args.carpeta)
    destino.mkdir(parents=True, exist_ok=True)
    for f in sorted(PLANTILLAS.iterdir()):
        if (destino / f.name).exists():
            continue
        if f.is_dir():
            shutil.copytree(f, destino / f.name)
        else:
            shutil.copy(f, destino / f.name)
        print(f"  + {destino / f.name}")
    print("Rellena los archivos (o sustitúyelos por las exportaciones del sistema de caja) y ejecuta «validar».\n"
          "La subcarpeta «ejemplo» muestra un negocio pequeño completo; no se importa.")
    return 0


def cmd_validar(args) -> int:
    url = args.db or os.environ.get("DB_URL_IMPORTADOR")
    conn = _conectar(url, "DB_URL_IMPORTADOR") if url else None
    try:
        _, informe = preparar(Path(args.carpeta), _ahora(args.ahora), conn, eltoque=False)
    finally:
        if conn is not None:
            conn.close()
    print(informe.texto(args.max_errores))
    return 1 if informe.errores else 0


def cmd_importar(args) -> int:
    from .escritura import escribir

    inicio = time.monotonic()
    with _conectar(args.db or os.environ.get("DB_URL_IMPORTADOR"), "DB_URL_IMPORTADOR") as conn:
        carga, informe = preparar(Path(args.carpeta), _ahora(args.ahora), conn, eltoque=args.eltoque)
        print(informe.texto(args.max_errores))
        if informe.errores and not args.omitir_errores:
            print("\nNo se ha importado nada. Corrige los errores o usa --omitir-errores para importar el resto.")
            return 1
        if not carga.productos:
            print("\nNo hay productos que importar.")
            return 1
        n = escribir(conn, carga, args.negocio or os.environ.get("NEGOCIO_NOMBRE"))
        neg_id = n.pop("negocio_id")
        primero = conn.execute("select min(id) from public.negocios").fetchone()[0]
    print(f"\nImportado en {time.monotonic() - inicio:.1f} s (negocio {neg_id}): "
          + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in n.items()))
    if neg_id != primero:
        print(f"Atención: la base de datos tiene varios negocios. El agente lee el de id {primero} salvo que su .env "
              f"tenga NEGOCIO_ID={neg_id}.")
    return 0


def cmd_instalar(args) -> int:
    with _conectar(args.db or os.environ.get("DB_URL_ADMIN"), "DB_URL_ADMIN") as conn:
        for f in sorted(MIGRACIONES.glob("*.sql")):
            ya = APLICADA.get(f.name)
            if ya and conn.execute(ya).fetchone()[0]:
                print(f"  = {f.name} (ya aplicada)")
                continue
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
            print(f"  + {f.name}")
    print("Esquema listo. Activa los usuarios con contraseña (ver docs/IMPORTACION.md §1).")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING"), format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="python -m agente_interno.importador",
                                 description="Importa los datos de un negocio desde archivos CSV o Excel.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plantillas", help="Copia las plantillas de los archivos a una carpeta.")
    p.add_argument("carpeta")
    for nombre, ayuda in (("validar", "Revisa los archivos sin escribir nada."),
                          ("importar", "Reconstruye los datos del negocio a partir de los archivos.")):
        q = sub.add_parser(nombre, help=ayuda)
        q.add_argument("carpeta")
        q.add_argument("--db", help="Cadena de conexión (por defecto, DB_URL_IMPORTADOR).")
        q.add_argument("--ahora", help="Momento de referencia ISO 8601 (pruebas). Por defecto, ahora.")
        q.add_argument("--max-errores", type=int, default=40)
        if nombre == "importar":
            q.add_argument("--negocio", help="Nombre del negocio (por defecto, NEGOCIO_NOMBRE o el único que haya).")
            q.add_argument("--omitir-errores", action="store_true", help="Importar aunque haya filas con errores (se descartan).")
            q.add_argument("--eltoque", action="store_true", help="Descargar de elTOQUE las tasas que falten (ELTOQUE_API_KEY).")
    i = sub.add_parser("instalar-esquema", help="Crea las tablas, herramientas y roles en una base de datos vacía.")
    i.add_argument("--db", help="Cadena de conexión de administrador (por defecto, DB_URL_ADMIN).")
    args = ap.parse_args(argv)
    try:
        return {"plantillas": cmd_plantillas, "validar": cmd_validar, "importar": cmd_importar,
                "instalar-esquema": cmd_instalar}[args.cmd](args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # errores de conexión o de permisos: mensaje corto, sin traza
        import psycopg

        if not isinstance(e, psycopg.Error):
            raise
        print(f"Error de base de datos: {str(e).strip()}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
