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

## Fase 3 — Métricas y reglas (todas las propuestas aprobadas)
- No disponible: beneficio neto (no hay gastos fijos; solo beneficio bruto), caducidades/lotes, clientes, precios de mercado (Agente Externo).
- Métricas: ventas día/semana/mes, ingresos USD y CUP, unidades, ticket medio, ventas por canal y forma de pago, coste de lo vendido, beneficio y margen bruto, más/menos vendidos, sin ventas, velocidad de venta, stock actual/mínimo, días de cobertura, riesgo de rotura, exceso, rotación, dinero inmovilizado, evolución vs periodo anterior y vs año anterior.
- Ventas netas = completadas − devoluciones (anuladas excluidas). Margen bruto = (ventas netas − coste) / ventas netas, en USD; en CUP con la tasa de cada venta.
- Velocidad = unidades últimos 30 días / 30. Cobertura = stock / velocidad. Rotación = coste vendido / inventario medio. Día comercial en America/Havana; semana empieza el lunes.
- Agotado: stock = 0. Stock bajo: stock ≤ stock mínimo. Stock mínimo: 7 días de venta (Mercado), 14 (Envíos). Plazo de reposición: 7 días (Mercado), 21 (Envíos). Riesgo de rotura: cobertura < plazo. Exceso: cobertura > 90 días. Sin movimiento: 0 ventas en 30 días con stock. Baja rotación: < 25 % de la media de su categoría.
- Prioritarios: top 20 % por ingresos (ABC) + básicos (comida y aseo).
- Anomalías: ventas del día ±30 % vs media del mismo día de la semana (4 semanas); anuladas > 3 % semanal; devoluciones > 5 % de un producto en 30 días; margen < 10 %; tasa elTOQUE ±5 % en una semana; producto activo sin precio vigente; stock sin ventas en 30 días.
- Horario: tienda física L–S 9:00–19:00, domingo 9:00–13:00; web 24 h.
- Márgenes objetivo: comida/combos 15–25 %, aseo 25–35 %, farmacia 30–40 %, ferretería 30–40 %, electrodomésticos 20–30 %, energía 20–30 %.
- Se siembran situaciones de prueba (agotados, excesos, devoluciones anómalas, semana de caída).

### Ajustes de mercado cubano para generar el historial
- Estacionalidad: diciembre y fin de año altos; fines de semana más fuertes; ventiladores/aires con pico junio–septiembre; energía (plantas, paneles, baterías, lámparas recargables) alta todo el año; comida y aseo estables.
- Picos: Día de las Madres (2.º domingo de mayo), primeros días de mes (remesas y cobros), 24–31 de diciembre.
- Días festivos con tienda física cerrada o reducida: 1 de enero, 1 de mayo, 25–27 de julio, 10 de octubre, 25 de diciembre.
- Apagones: algunos días con ventas físicas reducidas (sin afectar a la web).
- Formas de pago: mezcla de efectivo CUP, transferencia CUP (Transfermóvil/EnZona) y efectivo USD; pagos mixtos ocasionales.
- Tasas: histórico real diario de elTOQUE (`scripts/demo/datos/tasas_eltoque.csv`, 2025-10-01 a 2026-09-30).

### Carga de datos (fase 3 cerrada)
- Catálogo: opción (a) — 150 productos típicos del mercado cubano con categorías tipo Cuballama y precios USD estimados. Cuballama no se usó como fuente de datos (sus productos se cargan desde `/api/`, prohibido en su robots.txt).
- Proveedores ficticios: 8. Historial generado del 1/10/2025 al 30/9/2026 11:30 (La Habana): 22 711 ventas (~55–72/día), ~1,11 M USD netos.
- Generador y situaciones sembradas: `scripts/demo/` (ver README). El esquema temporal `gen` se eliminó de Supabase.

## Fase 4 — Telegram (todas las propuestas aprobadas)
- "Hoy" = fecha y hora actuales de La Habana (America/Havana). Implica que el negocio de demostración debe seguir recibiendo ventas cada día (proceso alimentador separado, fuera del alcance del agente) — a detallar en la fase 5.
- Mensajes proactivos: resumen diario a las 19:30 + alertas urgentes inmediatas (agotado o riesgo de rotura de producto prioritario, caída fuerte de ventas). Excesos, sin movimiento, margen bajo y devoluciones van en el resumen.
- Límites: máx. 3 alertas urgentes/día, sin repetir la misma alerta en 24 h, silencio 21:00–8:00 (se envía a las 8:00).
- Comandos: /resumen, /ventas (botones hoy/semana/mes), /stock, /producto <nombre>, /alertas, /ayuda + texto libre.
- Botones: solo de consulta (nunca acciones).
- Español de Cuba, tuteo, cercano y directo, sin tecnicismos.
- Cifras: USD primero y CUP entre paréntesis ("1 250,00 USD (≈ 927 500 CUP)"), CUP sin decimales, miles con espacio, coma decimal.
- Hechos sin marca; 📊 cálculo, 💡 inferencia, ❔ no disponible; siempre periodo y hora de los datos.
- Mensajes de 5–10 líneas, cifra clave arriba, emojis solo como iconos de sección, detalle bajo petición, solo texto en el MVP.
