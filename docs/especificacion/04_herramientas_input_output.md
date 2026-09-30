# 4. Input y output de cada herramienta

Convenciones: fechas `YYYY-MM-DD` interpretadas en **America/Havana** (`to` inclusivo); timestamps ISO 8601 con desplazamiento
(`-04:00` / `-05:00`); importes USD con 2 decimales; CUP enteros; porcentajes con 1 decimal.
Los nombres de campo están en inglés (estándar entre agentes); los textos, en español.
Las cifras de los ejemplos son **ilustrativas** salvo las de agosto de 2026 (ver valores de referencia en `10_casos_de_prueba.md`).

## 4.1 Sobre común de salida

```json
{
  "status": "ok | no_data | error",
  "tool": "get_sales_summary",
  "params": { "...": "parámetros efectivos tras aplicar valores por defecto" },
  "period": { "from": "2026-08-01", "to": "2026-08-31", "timezone": "America/Havana" },
  "data_as_of": "2026-09-30T11:28:40-04:00",
  "generated_at": "2026-09-30T11:30:02-04:00",
  "fx": { "date": "2026-09-30", "usd_cup": 741.74, "source": "elTOQUE" },
  "data": { },
  "kinds": { "data.totals.net_usd": "calculation", "data.totals.tickets": "fact" },
  "warnings": [ "1 producto activo sin precio" ]
}
```

Errores (sin detalles técnicos):

```json
{ "status": "error", "tool": "get_product", "error_code": "invalid_params | not_found | ambiguous | timeout | internal",
  "message": "No encontré ningún producto con ese código.", "generated_at": "..." }
```

`kinds` marca como `fact` los valores leídos tal cual (stock, precio vigente, fechas, conteos) y como `calculation` los derivados
(importes netos, márgenes, velocidades, coberturas, porcentajes). Las herramientas **nunca** devuelven `inference`: eso lo añade el modelo.

---

## 4.2 `get_business_summary`
**Input**
| Campo | Tipo | Obligatorio | Defecto |
|---|---|---|---|
| `date` | date | no | hoy (La Habana) |

**Output `data`**
```json
{
  "date": "2026-09-30", "as_of_hour": "11:28", "is_partial_day": true,
  "today": { "net_usd": 1551.20, "net_cup": 1150620, "tickets": 26, "units": 58, "avg_ticket_usd": 59.66,
             "gross_margin_pct": 24.1,
             "by_channel": [ { "channel": "tienda_fisica", "net_usd": 1011.00, "tickets": 18 },
                             { "channel": "web", "net_usd": 540.20, "tickets": 8 } ] },
  "expected": { "basis": "media de los 4 mismos días de la semana anteriores hasta la misma hora",
                "net_usd": 1480.00, "tickets": 24 },
  "vs_expected_pct": 4.8,
  "month_to_date": { "net_usd": 102467.20, "net_cup": 72950000, "vs_prev_month_same_days_pct": 3.9 },
  "alerts_count": { "urgent": 1, "high": 3, "medium": 4, "low": 2 },
  "fx_change_7d_pct": 4.1
}
```

## 4.3 `get_sales_summary`
**Input**
| Campo | Tipo | Obligatorio | Valores / defecto |
|---|---|---|---|
| `from` | date | sí | — |
| `to` | date | sí | ≥ `from`, rango ≤ 400 días |
| `group_by` | enum | no | `none` (defecto), `day`, `week`, `month`, `channel`, `payment_method`, `category` |
| `compare` | enum | no | `none` (defecto), `previous_period`, `previous_year` |
| `channel` | enum | no | `all` (defecto), `tienda_fisica`, `web` |

**Output `data`**
```json
{
  "totals": { "gross_usd": 101203.30, "returns_usd": 468.00, "net_usd": 100735.30, "net_cup": 67597940,
              "tickets": 1933, "units": 5120, "avg_ticket_usd": 52.36,
              "cogs_usd": 75681.25, "gross_profit_usd": 25054.05, "gross_margin_pct": 24.9,
              "voided_tickets": 20 },
  "groups": [ { "key": "2026-08-01", "net_usd": 3520.10, "net_cup": 2390000, "tickets": 66, "units": 170,
                "gross_margin_pct": 25.2 } ],
  "comparison": { "period": { "from": "2026-07-01", "to": "2026-07-31" },
                  "totals": { "net_usd": 104210.00, "tickets": 2050 },
                  "delta_pct": { "net_usd": -3.3, "tickets": -5.7 } }
}
```
Con `group_by = payment_method`, cada grupo es `{ "method": "transferencia", "currency": "CUP", "amount": 30500000, "amount_usd_equiv": 45120.00, "share_pct": 44.8 }`
(fuente: tabla de pagos; los pagos mixtos cuentan en cada método por su importe).

## 4.4 `get_top_products`
**Input**
| Campo | Tipo | Obligatorio | Valores / defecto |
|---|---|---|---|
| `from`, `to` | date | sí | — |
| `metric` | enum | no | `units` (defecto), `revenue`, `gross_profit` |
| `order` | enum | no | `top` (defecto), `bottom` |
| `limit` | int | no | 10 (1–50) |
| `category` | text | no | nombre de categoría o subcategoría |
| `include_zero_sales` | bool | no | `false`; con `order=bottom` conviene `true` |

**Output `data`**
```json
{ "items": [ { "rank": 1, "sku": "BEB-001", "name": "Refresco de lata 355 ml", "category": "Bebidas",
               "units": 393, "revenue_usd": 353.70, "gross_profit_usd": 72.10, "margin_pct": 20.4,
               "share_pct": 7.7 } ],
  "total_products_considered": 146 }
```

## 4.5 `find_products`
**Input**: `query` (text, 2–60 caracteres, obligatorio) · `limit` (int, defecto 5, máx. 10) · `include_inactive` (bool, defecto `false`)

**Output `data`**
```json
{ "matches": [ { "sku": "GRA-010", "name": "Aceite de girasol 1 L", "category": "Alimentos › Granos y básicos",
                 "active": true, "similarity": 0.62 },
               { "sku": "GRA-011", "name": "Aceite de soya 5 L", "category": "Alimentos › Granos y básicos",
                 "active": true, "similarity": 0.48 } ],
  "ambiguous": true }
```
`ambiguous = true` cuando hay más de una coincidencia con similitud ≥ 0,35 y la diferencia entre las dos primeras es < 0,15.

## 4.6 `get_product`
**Input**: `sku` (text, obligatorio; obtenido con `find_products`)

**Output `data`**
```json
{
  "sku": "GRA-010", "name": "Aceite de girasol 1 L", "category": "Alimentos", "subcategory": "Granos y básicos",
  "active": true, "unit": "unidad", "priority": true, "abc_class": "A",
  "price_usd": 3.80, "price_cup_today": 2820,
  "price_history": [ { "from": "2025-09-01", "to": null, "price_usd": 3.80 } ],
  "stock": 0, "min_stock": 49, "status": "agotado", "days_out_of_stock": 18,
  "velocity_30d": 1.63, "coverage_days": 0, "lead_time_days": 7,
  "pending_purchases": [],
  "last_sale_at": "2026-09-12T17:40:00-04:00",
  "sales_30d": { "units": 49, "net_usd": 186.20 },
  "margin_30d_pct": 19.1, "avg_cost_usd": 3.07,
  "returns_30d": { "units": 0, "return_pct": 0.0, "top_reason": null }
}
```
`status` ∈ `agotado`, `riesgo_rotura`, `stock_bajo`, `exceso`, `sin_movimiento`, `normal`, `inactivo` (se informa el más grave).

## 4.7 `get_product_history`
**Input**: `sku` (obligatorio) · `from`, `to` (obligatorios) · `granularity` (`day` | `week` | `month`, defecto `week`)

**Output `data`**
```json
{ "sku": "CLI-001", "name": "Ventilador de pedestal 18 pulgadas",
  "series": [ { "period": "2026-08-31", "units": 21, "net_usd": 945.00, "avg_price_usd": 45.00,
                "stock_end": 470, "purchases_received": 0 } ] }
```

## 4.8 `get_inventory_status`
**Input**
| Campo | Tipo | Valores / defecto |
|---|---|---|
| `filter` | enum | `all_issues` (defecto), `out_of_stock`, `low_stock`, `stockout_risk`, `overstock`, `no_movement` |
| `category` | text | opcional |
| `priority_only` | bool | `false` |
| `limit` | int | 50 (1–50) |

**Output `data`**
```json
{
  "items": [ { "sku": "GRA-012", "name": "Leche en polvo 1 kg", "category": "Alimentos", "priority": true,
               "status": "riesgo_rotura", "stock": 14, "min_stock": 28, "velocity_30d": 4.07,
               "coverage_days": 3.4, "lead_time_days": 7, "pending_qty": 0,
               "stock_value_usd": 99.40, "days_out_of_stock": null } ],
  "totals": { "by_status": { "agotado": 3, "riesgo_rotura": 5, "stock_bajo": 4, "exceso": 6, "sin_movimiento": 5 },
              "immobilized_value_usd": 31250.00,
              "total_stock_value_usd": 118400.00 }
}
```
`immobilized_value_usd` = valor a coste medio del stock en `exceso` + `sin_movimiento`.

## 4.9 `get_margin_analysis`
**Input**: `from`, `to` (obligatorios) · `group_by` (`product` | `category`, defecto `category`) · `below_threshold_pct` (numeric, opcional) · `limit` (defecto 20, máx. 50) · `order` (`asc` defecto | `desc`)

**Output `data`**
```json
{ "items": [ { "key": "GRA-013", "name": "Café molido 250 g", "net_usd": 540.00, "cogs_usd": 530.80,
               "gross_profit_usd": 9.20, "margin_pct": 1.7, "margin_prev_period_pct": 21.3,
               "avg_cost_change_pct": 22.9, "price_change_pct": 0.0 } ],
  "overall_margin_pct": 24.9 }
```

## 4.10 `get_alerts`
**Input**: `min_priority` (`low` defecto | `medium` | `high` | `urgent`) · `category` (opcional)

**Output `data`**
```json
{ "alerts": [ { "alert_key": "agotado_prioritario:GRA-010:2026-09-30", "rule": "agotado_prioritario",
                "priority": "urgent", "category": "inventario",
                "product": { "sku": "GRA-010", "name": "Aceite de girasol 1 L" },
                "title": "Aceite de girasol 1 L agotado",
                "detail": "Producto prioritario sin stock desde hace 18 días; vendía 1,6 u/día.",
                "current_value": 0, "threshold": 0, "detected_at": "2026-09-30T11:30:02-04:00" } ],
  "count_by_priority": { "urgent": 1, "high": 3, "medium": 4, "low": 2 } }
```
`alert_key` = `regla:sku|global:fecha` y sirve para no repetir alertas en 24 h. Reglas y prioridades: `05_reglas_de_negocio.md` §5.6.

## 4.11 `get_returns_and_voids`
**Input**: `from`, `to` (obligatorios) · `group_by` (`product` defecto | `reason` | `day`)

**Output `data`**
```json
{
  "voids": { "count": 38, "pct_of_tickets": 5.5, "amount_usd": 1830.00,
             "by_reason": [ { "reason": "Transferencia no confirmada", "count": 12 } ],
             "by_day": [ { "date": "2026-09-25", "count": 10, "pct": 11.9 } ] },
  "returns": { "units": 12, "amount_usd": 640.00,
               "by_product": [ { "sku": "ELE-002", "name": "Olla de presión eléctrica", "returned_units": 6,
                                 "sold_units": 23, "return_pct": 26.1, "top_reason": "Producto defectuoso",
                                 "restocked_units": 0 } ],
               "by_reason": [ { "reason": "Producto defectuoso", "units": 9 } ] }
}
```

## 4.12 `get_exchange_rate`
**Input**: `from`, `to` (opcionales; defecto últimos 30 días)

**Output `data`**
```json
{ "today": { "date": "2026-09-30", "usd_cup": 741.74, "source": "elTOQUE" },
  "series": [ { "date": "2026-09-01", "usd_cup": 680.60 } ],
  "change_pct": { "d7": 4.1, "d30": 9.0, "period": 9.0, "year": 70.5 },
  "impact": { "example_price_usd": 10.00, "price_cup_start": 6810, "price_cup_today": 7420,
              "note": "Los precios están fijados en USD: una subida de la tasa encarece en CUP todo el catálogo." } }
```

## 4.13 `get_data_quality`
**Input**: ninguno.

**Output `data`**
```json
{ "last_sale_at": "2026-09-30T11:28:40-04:00", "last_movement_at": "2026-09-30T11:28:40-04:00",
  "freshness_minutes": 2, "fx_last_date": "2026-09-30", "fx_missing_today": false,
  "active_without_price": [ { "sku": "ASE-016", "name": "Detergente líquido 3 L" } ],
  "inactive_with_stock": [ { "sku": "ELE-014", "name": "Sandwichera", "stock": 16 } ],
  "products_without_min_stock": [ { "sku": "ASE-016", "name": "Detergente líquido 3 L" } ],
  "stock_mismatch_count": 0,
  "overdue_purchases": [ { "supplier": "Electro Hogar Importaciones", "ordered_at": "2026-08-20", "days_overdue": 12 } ],
  "warnings": [ "1 producto activo sin precio: no se puede vender" ] }
```
`freshness_minutes > 120` durante el horario de apertura genera aviso "datos posiblemente desactualizados".
