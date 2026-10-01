"""Definición de las 12 herramientas para el modelo (04_herramientas_input_output.md)."""
from __future__ import annotations

FECHA = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$", "description": "Fecha AAAA-MM-DD (hora de La Habana)."}


def _obj(propiedades: dict, obligatorias: list[str] | None = None) -> dict:
    return {"type": "object", "properties": propiedades, "required": obligatorias or [], "additionalProperties": False}


HERRAMIENTAS: list[dict] = [
    {
        "name": "get_business_summary",
        "description": (
            "Estado de un día (por defecto hoy): ventas netas, tickets, margen y canales hasta la hora actual, "
            "comparado con lo esperado a la misma hora (media de los 4 mismos días de la semana anteriores); "
            "mes en curso frente al mes anterior; número de alertas por prioridad; tasa del día y su variación en 7 días. "
            "Úsala para 'cómo voy hoy', 'resumen', '¿qué pasó ayer?'."
        ),
        "input_schema": _obj({"date": FECHA}),
    },
    {
        "name": "get_sales_summary",
        "description": (
            "Ventas de un periodo: brutas, devoluciones, netas (USD y CUP), tickets, unidades, ticket medio, coste de lo "
            "vendido, beneficio y margen bruto, anuladas. Puede agrupar por día, semana, mes, canal, forma de pago o "
            "categoría, y comparar con el periodo anterior o el mismo periodo del año anterior. Si el periodo incluye hoy, "
            "los datos llegan hasta la hora actual."
        ),
        "input_schema": _obj({
            "from": FECHA, "to": FECHA,
            "group_by": {"type": "string", "enum": ["none", "day", "week", "month", "channel", "payment_method", "category"]},
            "compare": {"type": "string", "enum": ["none", "previous_period", "previous_year"]},
            "channel": {"type": "string", "enum": ["all", "tienda_fisica", "web"]},
        }, ["from", "to"]),
    },
    {
        "name": "get_top_products",
        "description": (
            "Ranking de productos de un periodo por unidades, ingresos netos o beneficio bruto, de más a menos ('top') "
            "o de menos a más ('bottom'). Con include_zero_sales=true incluye productos activos sin ventas."
        ),
        "input_schema": _obj({
            "from": FECHA, "to": FECHA,
            "metric": {"type": "string", "enum": ["units", "revenue", "gross_profit"]},
            "order": {"type": "string", "enum": ["top", "bottom"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "category": {"type": "string", "minLength": 2, "maxLength": 60, "description": "Categoría o subcategoría."},
            "include_zero_sales": {"type": "boolean"},
        }, ["from", "to"]),
    },
    {
        "name": "find_products",
        "description": (
            "Busca productos por nombre aproximado (tolera errores de escritura) o por código. Úsala SIEMPRE antes de "
            "consultar un producto que el dueño nombra. Si 'ambiguous' es true, pregunta cuál quiere."
        ),
        "input_schema": _obj({
            "query": {"type": "string", "minLength": 2, "maxLength": 60},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            "include_inactive": {"type": "boolean"},
        }, ["query"]),
    },
    {
        "name": "get_product",
        "description": (
            "Ficha completa de un producto por su código (sku): precio en USD y en CUP hoy, historial de precios, stock, "
            "stock mínimo, estado (agotado, riesgo de rotura, stock bajo, exceso, sin movimiento, normal), velocidad de "
            "venta, días que dura el stock, plazo de reposición, compras en camino, margen y devoluciones de 30 días."
        ),
        "input_schema": _obj({"sku": {"type": "string", "minLength": 3, "maxLength": 20}}, ["sku"]),
    },
    {
        "name": "get_product_history",
        "description": "Evolución de un producto por día, semana o mes: unidades, ventas netas, precio medio, stock al final y compras recibidas.",
        "input_schema": _obj({
            "sku": {"type": "string", "minLength": 3, "maxLength": 20}, "from": FECHA, "to": FECHA,
            "granularity": {"type": "string", "enum": ["day", "week", "month"]},
        }, ["sku", "from", "to"]),
    },
    {
        "name": "get_inventory_status",
        "description": (
            "Productos con problemas de inventario: agotados, riesgo de rotura, stock bajo, exceso de stock, sin "
            "movimiento; prioritarios primero. Incluye el dinero inmovilizado (exceso + sin movimiento) y el valor total del stock."
        ),
        "input_schema": _obj({
            "filter": {"type": "string", "enum": ["all_issues", "out_of_stock", "low_stock", "stockout_risk", "overstock", "no_movement"]},
            "category": {"type": "string", "minLength": 2, "maxLength": 60},
            "priority_only": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        }),
    },
    {
        "name": "get_margin_analysis",
        "description": (
            "Margen bruto por producto o categoría en un periodo, con el margen del periodo anterior y la variación del "
            "coste y del precio medio. Con below_threshold_pct filtra los que están por debajo de ese margen."
        ),
        "input_schema": _obj({
            "from": FECHA, "to": FECHA,
            "group_by": {"type": "string", "enum": ["product", "category"]},
            "below_threshold_pct": {"type": "number"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "order": {"type": "string", "enum": ["asc", "desc"]},
        }, ["from", "to"]),
    },
    {
        "name": "get_alerts",
        "description": (
            "Alertas activas calculadas con las reglas oficiales del negocio, ordenadas por prioridad (urgent, high, "
            "medium, low). Úsala para '¿hay algo raro?' o '¿qué debería saber?'."
        ),
        "input_schema": _obj({
            "min_priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
            "category": {"type": "string", "enum": ["ventas", "inventario", "rentabilidad", "devoluciones", "anulaciones", "tasa", "calidad_datos"]},
        }),
    },
    {
        "name": "get_returns_and_voids",
        "description": "Ventas anuladas (cantidad, %, motivos, canal y día) y devoluciones (unidades, importe, por producto con % sobre lo vendido y motivo) de un periodo.",
        "input_schema": _obj({
            "from": FECHA, "to": FECHA,
            "group_by": {"type": "string", "enum": ["product", "reason", "day"]},
        }, ["from", "to"]),
    },
    {
        "name": "get_exchange_rate",
        "description": "Tasa USD→CUP de elTOQUE: la de hoy, la serie del periodo (por defecto 30 días), variaciones y su efecto en los precios en CUP.",
        "input_schema": _obj({"from": FECHA, "to": FECHA}),
    },
    {
        "name": "get_data_quality",
        "description": "Frescura de los datos y problemas de calidad: última venta, falta de tasa, productos activos sin precio, desactivados con stock, compras retrasadas.",
        "input_schema": _obj({}),
    },
]

NOMBRES: frozenset[str] = frozenset(h["name"] for h in HERRAMIENTAS)
ESQUEMAS: dict[str, dict] = {h["name"]: h["input_schema"] for h in HERRAMIENTAS}
