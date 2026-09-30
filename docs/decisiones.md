# Decisiones de diseño — Agente Interno (MercadoAgentico)

Registro de lo validado en la entrevista por fases. No accesible para el agente.

## Fase 1 — Negocio
- MVP de producto replicable para tiendas cubanas; se demuestra con el negocio **MercadoAgentico**.
- 1 tienda física + 1 web, stock compartido, 40–80 ventas/día, 12 meses de historial (incluye devoluciones y anulaciones).
- Catálogo: 150 productos tomados de las páginas públicas de Cuballama (mezcla Mercado + Envíos). Sin marca Cuballama en la BD.
- Precios fijos en USD, cobrados en CUP a la tasa diaria de elTOQUE (`ELTOQUE_API_KEY`). Formas de pago: efectivo USD, efectivo CUP, transferencia CUP.
- Informes en CUP y USD. Único usuario: el dueño.
- Los datos operativos (stock, costes, ventas, compras, proveedores) son generados. El agente los trata como reales: la BD no contiene marcas de simulación. En demos comerciales se presenta como "negocio de demostración".

## Fase 2 — Base de datos
- PostgreSQL en Supabase, proyecto MercadoMVP (`btnkzxrkrqsgcuuxqtjd`). Esquema: `supabase/migrations/20260930000000_esquema_inicial.sql`.
- Sin tabla de clientes.
- Tasa fija por día (primera del día, tabla `tasas_cambio`, histórico real de elTOQUE); precio CUP redondeado hacia arriba a múltiplos de 10.
- Pagos mixtos permitidos; se guarda el importe neto aplicado (sin vuelto). Transferencia solo en CUP.
- Costes en USD, coste medio ponderado; cada línea de venta guarda el coste del momento.
- Todo se vende por unidades.
- RLS activado sin políticas; el acceso de solo lectura del agente se define en la fase 5.
- Datos (ventas, stock, compras) se generan tras la fase 3.
