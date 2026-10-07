# Pruebas

| Archivo | Bloque (10_casos_de_prueba.md) | Necesita |
|---|---|---|
| `test_herramientas_sql.py` | A — las 12 herramientas contra la BD (cifras comparadas con un cálculo independiente) | PostgreSQL con datos |
| `test_seguridad_sql.py` | C — solo lectura, sin acceso a tablas, timeout, inyección | PostgreSQL con datos |
| `test_servicio.py` | Bucle del agente (Claude simulado), filtro de salida, formato, límite de uso, planificador de alertas, autorización del bot | nada |
| `test_orquestador.py` | D — API del orquestador (contrato v1.0, 401, 409, caché) | PostgreSQL con datos |
| `test_importador.py` | Importador: lectura de CSV/Excel, conversión USD/CUP, stock y coste medio, errores por fila | nada |
| `test_importador_bd.py` | Importador contra una base nueva (`importador_prueba`): esquema, permisos, herramientas, reimportación | PostgreSQL (vacío basta) |
| `test_conversaciones_llm.py` | B — conversaciones reales con Claude | `ANTHROPIC_API_KEY` (tiene coste) |

## Base de datos local de pruebas
```bash
# PostgreSQL 16+ local en /var/tmp/pgtest (puerto 55432), base "mvp"
psql ... -f supabase/migrations/20260930000000_esquema_inicial.sql
psql ... -f scripts/demo/generador.sql
python3 scripts/demo/construir_carga.py | psql ...
psql ... -c "select gen.preparar()"
while read a b h; do psql ... -c "select gen.simular_rango('$a','$b',$h)"; done < scripts/demo/tramos.txt
psql ... -c "select gen.finalizar()" -c "drop schema gen cascade"
psql ... -f supabase/migrations/20260930100000_esquema_agente.sql
psql ... -f supabase/migrations/20260930100100_herramientas_agente.sql
psql ... -f supabase/migrations/20260930100200_roles_y_registro.sql
psql ... -c "alter role agente_lectura login"          # solo en la base de pruebas
```
Variables: `TEST_DB_URL_ADMIN` y `TEST_DB_URL_AGENTE` (por defecto, la base local de arriba). Las pruebas del importador
crean y borran su propia base en el servidor de `TEST_DB_URL_SERVIDOR` (por defecto, el mismo servidor local).
Las pruebas congelan la hora en el **30/9/2026 11:30** (La Habana).

```bash
.venv/bin/pytest            # todo menos las conversaciones con Claude
.venv/bin/pytest -m llm -s  # conversaciones (requiere ANTHROPIC_API_KEY)
```
