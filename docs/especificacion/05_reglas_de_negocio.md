# 5. Reglas de negocio

Todas las herramientas aplican estas definiciones. El agente **no** puede redefinirlas en una conversación;
si el dueño pide otra definición, el agente explica la oficial y, si procede, calcula la alternativa marcándola 📊 y diciendo en qué se diferencia.

## 5.1 Parámetros generales
| Parámetro | Valor |
|---|---|
| Negocio | MercadoAgentico (1 tienda física + 1 web, stock compartido) |
| Zona horaria | America/Havana. Día comercial = día natural en La Habana |
| Semana | Lunes a domingo |
| Moneda de referencia | USD (precios fijados en USD) |
| Moneda de cobro | CUP a la tasa diaria de elTOQUE, redondeo hacia arriba a múltiplos de 10 CUP |
| Formas de pago | Efectivo USD, efectivo CUP, transferencia CUP (Transfermóvil/EnZona); pagos mixtos permitidos |
| Horario tienda física | Lunes a sábado 9:00–19:00; domingo 9:00–13:00 |
| Horario web | Pedidos 24 h |
| Festivos (tienda cerrada) | 1/1, 1/5, 25–27/7, 10/10, 25/12 |

## 5.2 Líneas de producto y plazos
| Línea | Categorías | Plazo de reposición | Stock mínimo (regla de fijación) |
|---|---|---|---|
| Mercado | Alimentos, Bebidas, Combos, Aseo e higiene, Farmacia, Ferretería | 7 días | 7 días de venta media |
| Envíos | Energía, Climatización, Electrodomésticos, Electrónica, Movilidad | 21 días | 14 días de venta media |

Estos valores viven en una tabla de configuración `agente.config_categoria` (categoría → línea, plazo, básico), no en el código.

## 5.3 Ventas y rentabilidad
| Métrica | Definición |
|---|---|
| Venta válida | `ventas.estado = 'completada'`. Las **anuladas** nunca cuentan como venta |
| Ventas brutas | Σ `total_usd` (o `total_cup`) de ventas completadas con fecha en el periodo |
| Devoluciones del periodo | Σ `reembolso_usd` de devoluciones con fecha en el periodo (en CUP: unidades × `precio_unitario_cup` de la línea original) |
| **Ventas netas** | Ventas brutas − devoluciones del periodo |
| Tickets | Nº de ventas completadas |
| Ticket medio | Ventas brutas ÷ tickets |
| Unidades vendidas | Σ `cantidad` de líneas de ventas completadas (sin restar devoluciones) |
| Coste de lo vendido (COGS) | Σ cantidad × `coste_unitario_usd` de las líneas − coste de las unidades devueltas **que reingresan al stock** |
| **Beneficio bruto** | Ventas netas − COGS |
| **Margen bruto %** | Beneficio bruto ÷ ventas netas × 100 |
| Margen en CUP | Se calcula con la tasa guardada en cada venta (nunca con la tasa de hoy) |
| Beneficio neto | ❔ **No disponible** (no hay gastos fijos registrados) |
| Coste unitario | Coste medio ponderado (se actualiza con cada compra recibida; cada línea de venta guarda el del momento) |

## 5.4 Inventario
| Métrica / estado | Definición |
|---|---|
| Velocidad de venta | Unidades vendidas en los **últimos 30 días** ÷ 30 |
| Días de cobertura | Stock actual ÷ velocidad (si velocidad = 0 → "sin ventas", no se calcula) |
| Compra en camino | Compras en estado `pendiente` |
| **Agotado** | Producto activo con stock = 0 **y** ventas en los últimos 60 días (si no, "agotado sin demanda reciente", prioridad baja) |
| **Stock bajo** | 0 < stock ≤ stock mínimo |
| **Riesgo de rotura** | Stock > 0 y (stock + compras en camino) ÷ velocidad < plazo de reposición |
| **Exceso de stock** | Días de cobertura > 90 |
| **Sin movimiento** | Stock > 0 y 0 ventas en 30 días (productos dados de alta hace ≥ 30 días) |
| **Baja rotación** | Velocidad < 25 % de la velocidad media de su categoría (productos con ≥ 30 días de alta) |
| Rotación | COGS del periodo ÷ valor medio del inventario a coste |
| Dinero inmovilizado | Stock × coste medio de los productos en exceso + sin movimiento |
| Estado más grave | agotado > riesgo_rotura > stock_bajo > exceso > sin_movimiento > normal |

## 5.5 Productos prioritarios
Un producto es **prioritario** si cumple cualquiera de:
1. **Clase A (ABC):** está en el 20 % de productos que más ingresos netos generaron en los últimos 90 días.
2. **Básico:** pertenece a Alimentos (Cárnicos y congelados, Granos y básicos, Despensa y conservas) o a Aseo e higiene.

Sus alertas salen siempre antes que las demás.

## 5.6 Reglas de alerta
| Regla (`rule`) | Condición | Prioridad | Mínimo de muestra |
|---|---|---|---|
| `agotado_prioritario` | Agotado y prioritario | **urgent** | — |
| `riesgo_rotura_prioritario` | Riesgo de rotura y prioritario | **urgent** | velocidad ≥ 0,2 u/día |
| `caida_ventas_dia` | Ventas netas del día ≤ −30 % frente a lo esperado a la misma hora (media de los 4 mismos días de la semana anteriores). Se evalúa desde las 12:00 y al cierre | **urgent** | lo esperado ≥ 300 USD |
| `datos_desactualizados` | Sin ventas ni movimientos en > 120 min en horario de apertura, o sin tasa del día | high | — |
| `agotado` | Agotado, no prioritario | high | — |
| `riesgo_rotura` | Riesgo de rotura, no prioritario | high | velocidad ≥ 0,2 u/día |
| `devoluciones_anomalas` | Devoluciones > 5 % de las unidades vendidas en 30 días | high | ≥ 3 unidades devueltas |
| `anulaciones_altas` | Anuladas > 3 % de los tickets de los últimos 7 días | high | ≥ 100 tickets |
| `margen_bajo_prioritario` | Margen 30 días < 10 % en producto prioritario | high | ≥ 10 unidades vendidas |
| `tasa_variacion` | La tasa USD→CUP varía ≥ 5 % en 7 días | high | — |
| `producto_sin_precio` | Producto activo sin precio vigente | high | — |
| `stock_bajo` | Stock bajo (sin riesgo de rotura) | medium | — |
| `margen_bajo` | Margen 30 días < 10 % en producto o categoría no prioritarios | medium | ≥ 10 unidades |
| `exceso_stock` | Exceso de stock | medium | — |
| `sin_movimiento` | Sin movimiento | medium | — |
| `pico_ventas_dia` | Ventas del día ≥ +30 % frente a lo esperado | medium | lo esperado ≥ 300 USD |
| `baja_rotacion` | Baja rotación | low | — |
| `inactivo_con_stock` | Producto desactivado con stock > 0 | low | — |
| `compra_retrasada` | Compra pendiente con más días que el plazo de su línea + 7 | low | — |
| `agotado_sin_demanda` | Agotado sin ventas en 60 días | low | — |

## 5.7 Envío de alertas por Telegram
- **Inmediatas:** solo prioridad `urgent`. Máximo **3 al día**; la misma `alert_key` no se repite en **24 h**.
- **Silencio 21:00–8:00:** lo detectado en ese horario se envía a las 8:00.
- **Resto de prioridades:** van en el **resumen diario de las 19:30**, ordenadas por prioridad.
- Revisión automática cada 30 minutos, de 8:00 a 21:00.

## 5.8 Estimaciones
- Solo bajo petición del dueño. Método simple y explicable: mismo periodo del año anterior (si existe) ajustado por la tendencia de los últimos 3 meses frente a esos mismos meses del año anterior; si no hay histórico suficiente, media de los últimos 3 meses.
- Siempre marcadas 💡, con el método en una frase y sin decimales falsos (redondear a centenas de USD).

## 5.9 Reglas pendientes de definir en futuras versiones
- Gastos fijos (para beneficio neto).
- Caducidades y lotes.
- Stock por ubicación (si algún cliente separa tienda y web).
- Umbrales personalizados por cliente (hoy son globales).
