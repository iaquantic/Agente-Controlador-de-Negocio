# 7. Contrato con Telegram

## 7.1 Canal
- Chat **privado** con el bot. Sin grupos. Único usuario autorizado: `TELEGRAM_OWNER_ID`.
- Idioma: español de Cuba, **tuteo**, tono cercano, profesional y directo. Sin tecnicismos
  (no "SKU", "cobertura", "COGS": sí "te quedan unos 5 días de aceite", "lo que te costó la mercancía vendida").
- Formato de envío: HTML de Telegram (`<b>`, `<i>`), sin tablas; listas con "•".
- Longitud: **5–10 líneas** por mensaje; cifra clave arriba; detalle bajo petición ("¿quieres el desglose?").
- Emojis solo como iconos de sección (📈 ventas, 📦 stock, 💰 margen, ⚠️ alerta, 💱 tasa) y las marcas de tipo.
- Solo texto en el MVP.

## 7.2 Cifras
| Elemento | Formato | Ejemplo |
|---|---|---|
| Importes | USD primero, CUP entre paréntesis | `1 250,00 USD (≈ 927 500 CUP)` |
| USD | 2 decimales, miles con espacio, coma decimal | `100 735,30 USD` |
| CUP | sin decimales | `67 597 940 CUP` |
| Porcentajes | 1 decimal | `24,9 %` |
| Unidades | enteros | `393 u` |
| Fechas | día y mes en texto | `30 sep`, `martes 29 sep` |
| Horas | 24 h, hora de La Habana | `11:28` |

## 7.3 Marcas de tipo de información
| Tipo | Marca | Ejemplo |
|---|---|---|
| Hecho | (ninguna) | `Stock de aceite: 0 u` |
| Cálculo | 📊 | `📊 Margen de agosto: 24,9 %` |
| Inferencia | 💡 | `💡 Probablemente por el apagón de la tarde` |
| No disponible | ❔ | `❔ No tengo los gastos fijos: no puedo darte el beneficio neto` |

Cada respuesta termina con la **referencia temporal** en cursiva: `<i>Datos de hoy hasta las 11:28 · tasa 741,74 CUP/USD</i>`.

## 7.4 Comandos
| Comando | Herramientas | Respuesta | Botones |
|---|---|---|---|
| `/start` | — | Saludo breve + qué puedo hacer + `/ayuda` | [Resumen] [Alertas] |
| `/resumen` | `get_business_summary`, `get_alerts` | Ventas de hoy vs lo esperado, mes en curso, alertas urgentes/altas, tasa | [Ver alertas] [Stock] [Esta semana] |
| `/ventas` | `get_sales_summary` | Pregunta el periodo con botones; por defecto hoy | [Hoy] [Semana] [Mes] [Mes pasado] |
| `/stock` | `get_inventory_status` | Agotados, riesgo de rotura y stock bajo (prioritarios primero) | [Excesos] [Sin movimiento] |
| `/producto <nombre>` | `find_products`, `get_product` | Ficha breve; si hay varias coincidencias, botones para elegir | [Historial] [Margen] |
| `/alertas` | `get_alerts` | Alertas activas por prioridad (máx. 8; el resto, "y N más") | [Urgentes] [Todas] |
| `/ayuda` | — | Ejemplos de preguntas y comandos | — |

Sin argumento, `/producto` pregunta "¿Qué producto quieres ver?".
Los botones son **solo de consulta** (`callback_data` = consulta predefinida); **nunca ejecutan acciones**.

## 7.5 Texto libre
Cualquier mensaje que no sea comando se trata como pregunta al agente (casos de `docs/casos_de_uso.md`).
Se mantiene un historial corto (últimos 6 intercambios, máx. 2 h) para preguntas de seguimiento ("¿y la semana pasada?").

## 7.6 Mensajes proactivos
**Resumen diario — 19:30**
```
📈 <b>Resumen del martes 29 sep</b>
Vendiste 1 678 USD (≈ 1 258 500 CUP) en 39 ventas.
📊 Un 48 % menos de lo normal para un martes.
💡 Coincide con menos ventas en tienda física; la web fue normal.

⚠️ <b>Atención</b>
• Aceite de girasol 1 L agotado desde hace 17 días (producto básico).
• Leche en polvo: te quedan unos 3 días.
• Café: 📊 margen del 1,7 % este mes (el coste subió y el precio no).

<i>Datos hasta las 19:00 · tasa 750,00 CUP/USD</i>
[Ver alertas] [Stock] [Esta semana]
```
*(Ejemplo ilustrativo de formato; las cifras reales las da la BD.)*

**Alerta urgente**
```
⚠️ <b>Aceite de girasol 1 L agotado</b>
Es un producto básico y vendías 1,6 u/día.
No hay compras en camino.
<i>Detectado a las 11:30</i>
[Ver producto] [Stock]
```

## 7.7 Límites y silencios
- Alertas urgentes: máx. **3/día**, sin repetir la misma en **24 h**.
- Silencio **21:00–8:00**: lo pendiente se envía a las 8:00 en un solo mensaje.
- Consultas del dueño: máx. **30/hora**.

## 7.8 Respuestas estándar
| Situación | Respuesta |
|---|---|
| Usuario no autorizado | "Este asistente es privado. No estás autorizado." |
| Petición de escritura ("sube el precio…") | "Solo puedo consultar y analizar, no puedo cambiar precios, stock ni ventas. Si quieres, te enseño cómo ha ido el café para que decidas el precio." |
| Fuera de alcance (competencia, mercado) | "❔ No tengo información del mercado ni de la competencia; solo conozco los datos de tu negocio." |
| Error técnico / timeout | "Ahora mismo no puedo consultar los datos. Inténtalo en unos minutos." |
| Datos desactualizados | Responde + "⚠️ Los últimos datos son de las HH:MM; puede que falten ventas recientes." |
| Producto ambiguo | "Encontré varios: [botón A] [botón B] ¿Cuál?" |
| Límite de uso | "Has llegado al límite de consultas por hora. Vuelve a intentarlo en unos minutos." |
