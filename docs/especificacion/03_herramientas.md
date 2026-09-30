# 3. Lista de herramientas

Principios:
- **Solo lectura.** Cada herramienta es una función del esquema `agente` en PostgreSQL (`STABLE`, `SECURITY DEFINER`, propietaria sin permisos de escritura). El rol `agente_lectura` solo tiene `EXECUTE` sobre ellas.
- **Sin SQL libre.** El modelo nunca escribe SQL; solo elige herramienta y parámetros.
- **Parámetros validados** en el servicio (esquema estricto) y otra vez en la función.
- **Definiciones únicas**: todas las métricas usan las reglas de `05_reglas_de_negocio.md`.
- **Salida JSON** con sobre común (ver 4.1): periodo, hora de los datos, tasa, avisos y tipo de cada dato.
- Límites: rango máximo de fechas 400 días; `limit` ≤ 50; `statement_timeout` 10 s.

| # | Herramienta | Propósito | Casos de uso |
|---|---|---|---|
| 1 | `get_business_summary` | Estado del día frente a lo esperado, mes en curso, alertas y tasa | 1, 22, resumen 19:30 |
| 2 | `get_sales_summary` | Ventas de un periodo, agrupadas y comparadas | 2–7, 18, 28 |
| 3 | `get_top_products` | Ranking de productos por unidades, ingresos o beneficio | 8, 9, 10 |
| 4 | `find_products` | Búsqueda aproximada por nombre (pg_trgm) | apoyo a 11, 12, 17 |
| 5 | `get_product` | Ficha completa de un producto | 11, 17 |
| 6 | `get_product_history` | Serie temporal de ventas y stock de un producto | 12 |
| 7 | `get_inventory_status` | Agotados, stock bajo, riesgo de rotura, exceso, sin movimiento, dinero inmovilizado | 13–16 |
| 8 | `get_margin_analysis` | Margen por producto o categoría | 19, 20 |
| 9 | `get_alerts` | Evaluación determinista de todas las reglas de alerta | 22, alertas automáticas |
| 10 | `get_returns_and_voids` | Devoluciones y anulaciones | 23, 24 |
| 11 | `get_exchange_rate` | Tasa elTOQUE actual, evolución e impacto | 21 |
| 12 | `get_data_quality` | Frescura y problemas de calidad de datos | control en todas |

## Uso previsto por el agente
- Producto mencionado por nombre → `find_products` primero; si hay varias coincidencias razonables, preguntar al dueño.
- "¿Hay algo raro?" → `get_alerts` + `get_business_summary`.
- Preguntas de "hoy" → `get_business_summary` (compara con lo esperado a la misma hora).
- Toda respuesta con cifras → revisar `warnings` del sobre y `get_data_quality` si los datos parecen desactualizados.
- Estimaciones → `get_sales_summary` del mismo periodo del año anterior y de los últimos meses; el modelo calcula una proyección simple y la marca 💡.

## Qué no existe (a propósito)
Herramientas de escritura, SQL libre, acceso a `registro`, `simulador` o credenciales, exportación masiva de datos.
