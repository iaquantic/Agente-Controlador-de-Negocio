# Datos de demostración de MercadoAgentico

Genera el catálogo y 12 meses de historial (1/10/2025 – 30/9/2026 11:30, hora de La Habana) en la BD.
Todo el código de generación vive en el esquema temporal `gen`, que se elimina al terminar:
el agente nunca ve rastro de que los datos son generados.

## Archivos
- `datos/catalogo.csv`: 150 productos típicos del mercado cubano (precios USD estimados, no copiados de ninguna tienda).
- `datos/tasas_eltoque.csv`: tasa USD→CUP real de elTOQUE de cada día (08:00). Se regenera con
  `python3 descargar_tasas.py 2025-10-01 2026-09-30 datos/tasas_eltoque.csv` (requiere `ELTOQUE_API_KEY`).
- `construir_carga.py`: convierte los CSV en SQL (`gen.catalogo` y `tasas_cambio`).
- `generador.sql`: funciones del simulador y situaciones sembradas (`gen.escenario`, `gen.compras_especiales`).
- `tramos.txt`: tramos de simulación (desde, hasta, hora de corte del último día).

## Procedimiento (sobre el esquema vacío de `supabase/migrations`)
1. Ejecutar `generador.sql`.
2. Ejecutar la salida de `python3 construir_carga.py`.
3. `select gen.preparar();`
4. Para cada línea de `tramos.txt`, **en serie** (nunca en paralelo): `select gen.simular_rango('desde', 'hasta', hora);`
5. `select gen.finalizar();` y `drop schema gen cascade;`

## Comprobaciones tras generar
Stock = suma de movimientos; stock acumulado nunca negativo; pagos = total de cada venta; tasa de cada venta =
tasa del día; precio CUP = USD × tasa redondeado hacia arriba a 10; sin fechas posteriores a la hora de corte.

## Situaciones sembradas (para probar al agente)
| Situación | Productos |
|---|---|
| Agotado (proveedor deja de servir) | Aceite de girasol 1 L, Estación de energía 300 Wh (con compra pendiente) |
| Riesgo de rotura | Leche en polvo 1 kg, Ventilador recargable 16" |
| Exceso de stock | Ventilador de pedestal 18", Aire split 1 ton, Televisor 43", Pintura blanca |
| Sin movimiento con stock | Freidora de aire 5 L, Batidora de vaso, Triciclo eléctrico |
| Margen < 10 % (subida de coste sin subir precio) | Café molido 250 g, Huevos cartón 30 u |
| Devoluciones anómalas (defecto) | Olla de presión eléctrica |
| Descatalogados (activo = false) | Tablet 10", Sandwichera, Vino tinto |
| Producto activo sin precio | Detergente líquido 3 L (alta 26/9/2026) |
| Anulaciones altas | Semana 21–27/9/2026 (~6 %) |
| Caída de ventas | Martes 29/9/2026 (ayer), semana de apagones 10–16/8/2026 |
| Temporada | Combo Día de las Madres (agotado tras mayo), Combo fin de año |

La carga en Supabase (MercadoMVP) se hizo el 30/9/2026 con una versión previa de este generador, a la que
después se aplicaron las mismas correcciones que hoy incluye el script (recepción de compras a las 06:30,
devoluciones sembradas deterministas, sin devoluciones posteriores a la hora de corte). Resultado verificado
con las comprobaciones de arriba: 22 711 ventas, 61 976 líneas, 23 270 pagos, 330 devoluciones, 921 compras.
