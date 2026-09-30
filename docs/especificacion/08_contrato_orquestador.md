# 8. Contrato con el Agente Orquestador (v1.0)

## 8.1 Transporte
- `POST /v1/consulta` en la red interna del VPS. Cabecera `Authorization: Bearer <ORQUESTADOR_TOKEN>`. `Content-Type: application/json`.
- Tiempo máximo de respuesta: **30 s**. Informes predefinidos en caché **5 min**; preguntas libres y herramientas sin caché.
- El Agente Interno **solo informa**: nunca envía mensajes al dueño a petición del orquestador (v1).
- Cada petición se registra en `registro.interacciones` (canal `orquestador`).
- Esquemas JSON formales: `docs/especificacion/schemas/orquestador_request.schema.json` y `orquestador_response.schema.json`.

## 8.2 Petición

```json
{
  "request_id": "5b1c0f3e-7d7a-4f55-9a0e-2c9a1c1d8f10",
  "version": "1.0",
  "type": "report",
  "report": "inventario",
  "period": { "from": "2026-09-01", "to": "2026-09-30" },
  "requested_at": "2026-09-30T19:30:00-04:00"
}
```

| Campo | Obligatorio | Valores |
|---|---|---|
| `request_id` | sí | UUID (se devuelve igual) |
| `version` | sí | `1.0` |
| `type` | sí | `report` · `question` · `tool` |
| `report` | si `type=report` | `estado_general` · `ventas` · `inventario` · `rentabilidad` · `alertas` · `calidad_datos` |
| `question` | si `type=question` | Texto en español (≤ 500 caracteres) |
| `tool` | si `type=tool` | `{ "name": "<una de las 12>", "params": { ... } }` (parámetros de `04_herramientas_input_output.md`) |
| `period` | no | `{from, to}`; por defecto: hoy (estado_general, alertas, calidad_datos) o mes en curso (resto) |
| `requested_at` | sí | ISO 8601 |

### Informes predefinidos
| `report` | Herramientas | Contenido |
|---|---|---|
| `estado_general` | business_summary, alerts, data_quality | Día y mes en curso, alertas urgentes/altas, tasa |
| `ventas` | sales_summary (compare previous_period, group_by channel), top_products | Totales, canales, top 5 |
| `inventario` | inventory_status (all_issues), alerts (inventario) | Estados, dinero inmovilizado, productos críticos |
| `rentabilidad` | margin_analysis (category y product < 10 %), sales_summary | Margen global, por categoría, productos con margen bajo |
| `alertas` | alerts | Todas las alertas activas |
| `calidad_datos` | data_quality | Frescura, huecos, incoherencias |

## 8.3 Respuesta

```json
{
  "request_id": "5b1c0f3e-7d7a-4f55-9a0e-2c9a1c1d8f10",
  "version": "1.0",
  "status": "ok",
  "summary": "3 productos agotados (1 básico), 5 en riesgo de rotura y 31 250 USD inmovilizados en exceso de stock.",
  "period": { "from": "2026-09-01", "to": "2026-09-30", "timezone": "America/Havana" },
  "metrics": {
    "immobilized_value_usd": { "value": 31250.00, "unit": "USD", "kind": "calculation",
                               "definition": "stock × coste medio de productos en exceso o sin movimiento" },
    "out_of_stock_count":    { "value": 3, "unit": "productos", "kind": "fact" }
  },
  "findings": [
    { "id": "F1", "kind": "fact", "category": "inventario",
      "title": "Aceite de girasol 1 L agotado", "detail": "Sin stock desde hace 18 días; sin compras en camino.",
      "evidence": { "sku": "GRA-010", "stock": 0, "days_out_of_stock": 18, "velocity_30d": 1.63 },
      "confidence": "high" },
    { "id": "F2", "kind": "inference", "category": "inventario",
      "title": "Posible problema de suministro del aceite",
      "detail": "El proveedor no ha servido desde el 10 de agosto.",
      "evidence": { "last_purchase_received": "2026-08-08" }, "confidence": "medium" }
  ],
  "alerts": [
    { "id": "A1", "alert_key": "agotado_prioritario:GRA-010:2026-09-30", "rule": "agotado_prioritario",
      "priority": "urgent", "category": "inventario",
      "product": { "sku": "GRA-010", "name": "Aceite de girasol 1 L" },
      "title": "Aceite de girasol 1 L agotado", "current_value": 0, "threshold": 0,
      "detected_at": "2026-09-30T19:30:02-04:00" }
  ],
  "not_available": [],
  "data_quality": { "last_data_at": "2026-09-30T19:02:11-04:00", "freshness_minutes": 28,
                    "fx": { "date": "2026-09-30", "usd_cup": 741.74, "source": "elTOQUE" },
                    "warnings": [ "1 producto activo sin precio" ] },
  "tools_used": [ "get_inventory_status", "get_alerts" ],
  "generated_at": "2026-09-30T19:30:04-04:00"
}
```
*(Cifras ilustrativas.)*

| Campo | Descripción |
|---|---|
| `status` | `ok` · `partial` (alguna herramienta falló o hay datos incompletos) · `no_data` · `out_of_scope` · `error` |
| `summary` | 1–3 frases en español, sin formato Telegram |
| `metrics` | Mapa `nombre → {value, unit, kind, definition?, value_cup?}`; `kind` ∈ `fact`, `calculation` |
| `findings` | Hallazgos: `kind` ∈ `fact`, `calculation`, `inference`; `confidence` ∈ `high`, `medium`, `low` (obligatoria en `inference`) |
| `alerts` | Salida de `get_alerts` (misma forma) |
| `not_available` | `[{item, reason}]`: lo pedido que no existe en la BD o está fuera de alcance |
| `data_quality` | Frescura, tasa usada y avisos |
| `tools_used` | Herramientas ejecutadas |
| `generated_at` | ISO 8601, hora de La Habana |

Error:
```json
{ "request_id": "5b1c0f3e-7d7a-4f55-9a0e-2c9a1c1d8f10", "version": "1.0", "status": "error",
  "error": { "code": "invalid_request", "message": "La petición no incluye 'report'." },
  "generated_at": "2026-09-30T19:30:01-04:00" }
```
`error.code` ∈ `unauthorized`, `invalid_request`, `unsupported_version`, `timeout`, `internal`.
Códigos HTTP: 200 (`ok`/`partial`/`no_data`/`out_of_scope`), 400 (`invalid_request`), 401 (`unauthorized`), 409 (`unsupported_version`), 504 (`timeout`), 500 (`internal`).

## 8.4 Reglas del contrato
- Nombres de campo en **inglés**; textos en **español**.
- Importes en USD con `value_cup` opcional; porcentajes como número (24.9, no "24,9 %").
- Una **pregunta** (`type=question`) usa el mismo agente y herramientas que Telegram, pero responde en este JSON (sin HTML ni emojis).
- Peticiones de escritura → `status: out_of_scope` y `not_available: [{item, reason: "el Agente Interno es de solo lectura"}]`.
- **Versionado:** añadir campos no rompe (sigue `1.x`); cambiar o quitar campos exige `2.0`. Versión no soportada → 409.
