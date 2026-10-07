# Importar los datos de un negocio real

El Agente Interno lee la base de datos del negocio (catálogo, ventas, compras, inventario, tasas). El **importador**
la llena a partir de archivos CSV o Excel que el cliente exporta de su sistema de caja o de sus hojas de cálculo.

```
carpeta del cliente (CSV / Excel) ──► importador ──► base de datos ──► Agente Interno ──► Agente Central / bot
```

**La carpeta es la fuente de verdad.** Cada importación reconstruye las ventas, compras, devoluciones, precios e
inventario del negocio a partir de *todos* los archivos de la carpeta. Importar dos veces da el mismo resultado, y
corregir un dato es tan simple como volver a exportar el archivo y repetir la importación. No se borra nada de la
carpeta: el historial completo debe seguir ahí. Un año de ventas (~22 000 tickets, ~56 000 líneas) se importa en
unos 5 segundos.

## 1. Preparar la base de datos de un cliente nuevo (una vez)

Cada cliente tiene su propia base de datos: un proyecto de Supabase o un PostgreSQL 15+.

```bash
# Con la cadena de conexión de administrador (Supabase → Connect → Session pooler, usuario postgres)
DB_URL_ADMIN="postgresql://postgres.<ref>:<contraseña>@<host>:5432/postgres" \
  python -m agente_interno.importador instalar-esquema
```

Crea las tablas, las 12 herramientas del agente y los roles. Se puede repetir sin riesgo: salta lo que ya existe.
Después, en el editor SQL, activa los usuarios con contraseñas largas inventadas por ti (nunca en el repositorio ni en un chat):

```sql
alter role agente_importador with login password 'CONTRASEÑA-LARGA-1';   -- escribe los datos del negocio
alter role agente_lectura    with login password 'CONTRASEÑA-LARGA-2';   -- lo usa el agente (solo lectura)
alter role agente_registro   with login password 'CONTRASEÑA-LARGA-3';   -- registro de uso del agente
```

En el `.env` del servidor: `DB_URL_IMPORTADOR` (usuario `agente_importador.<ref>` en Supabase), `DB_URL_AGENTE`,
`DB_URL_REGISTRO` y `NEGOCIO_NOMBRE`. **Quita `AGENTE_AHORA_FIJA`**: con datos reales el agente usa la hora real.

El rol `agente_importador` solo puede escribir las tablas del negocio: no ve el registro de conversaciones ni ejecuta
las herramientas del agente.

## 2. Preparar los archivos

```bash
python -m agente_interno.importador plantillas datos/importar
```

Crea en la carpeta una plantilla vacía de cada archivo y la subcarpeta `ejemplo/` con un negocio pequeño completo
(las subcarpetas no se importan). Los archivos pueden ser:

- **CSV** separado por `,` o `;`, en UTF-8 o en la codificación de Excel en español.
- **Excel** (`.xlsx`): cada hoja se importa según su nombre (`Productos`, `Ventas`…), o según el nombre del archivo
  si solo tiene una hoja.

**El nombre del archivo dice qué contiene**: `productos.csv`, `ventas.csv`, `ventas_2026-09.csv`,
`ventas_2026-10.xlsx`… Se leen en orden alfabético y, si un ticket o una compra aparecen en dos archivos, **manda el
último**. Por eso conviene nombrarlos por fecha (`ventas_2026-10-05.csv`).

Las columnas se reconocen sin importar mayúsculas, tildes ni espacios, y con los sinónimos habituales ("Código" = sku,
"Existencia" = stock, "Ticket" = número, "Forma de pago" = método de pago…). Si el sistema de caja usa otros nombres,
un archivo `mapeo.json` en la carpeta los traduce:

```json
{"ventas": {"Nro Doc": "numero", "Art": "sku"}, "productos": {"Descripción larga": "nombre"}}
```

Formatos: números con coma o punto decimal (`1,20`, `1.234,56`); fechas `dd/mm/aaaa` o `aaaa-mm-dd`, con hora
opcional (`04/10/2026 14:30`, también en columna `hora` aparte). Sin zona horaria se entiende **hora de La Habana**.
Un número con tres cifras tras el separador (`1.250`) se lee como miles: las cantidades se venden por unidades.

### Archivos y columnas

Obligatorias en **negrita**. Las demás tienen el valor por defecto indicado.

**`productos`** — el catálogo. Imprescindible.

| Columna | Qué es | Por defecto |
|---|---|---|
| **sku** | Código del producto | |
| **nombre** | Nombre | |
| **categoria** | Categoría (Alimentos, Aseo…) | |
| subcategoria | Subcategoría | la categoría |
| precio + moneda (o precio_usd / precio_cup) | Precio de venta actual | el de su última venta |
| coste (o coste_usd / coste_cup) | Coste unitario | el de su primera compra |
| stock + fecha_stock | Existencias en esa fecha (equivale a un conteo) | — |
| stock_minimo | Stock mínimo | 0 |
| activo | sí / no | sí |
| unidad | Unidad de venta | unidad |
| alta | Fecha de alta | su primer movimiento |

**`ventas`** — una fila por línea de ticket. Imprescindible.

| Columna | Qué es | Por defecto |
|---|---|---|
| numero | Número de ticket (las filas con el mismo número forman un ticket) | cada fila es un ticket |
| **fecha** (+ hora) | Momento de la venta | sin hora: 12:00 |
| **sku** | Código del producto (si no está en el catálogo, se crea en «Sin categoría»; ayuda una columna `nombre`) | |
| **cantidad** | Unidades | |
| precio o importe | Precio unitario, o importe de la línea | |
| moneda | USD o CUP | USD |
| tasa | Tasa USD→CUP aplicada | la del día (tasas) |
| canal | tienda / web | tienda |
| metodo_pago | efectivo / transferencia (Transfermóvil, EnZona…). Una transferencia va en CUP | efectivo |
| estado | completada / anulada | completada |
| anulada_en, motivo_anulacion | Cuándo y por qué se anuló | la fecha del ticket |
| coste_unitario_usd | Coste de lo vendido | coste medio en ese momento |

**`compras`** — entradas de mercancía. Muy recomendable (da el coste y el stock).

| Columna | Qué es | Por defecto |
|---|---|---|
| referencia | Número de factura o pedido (las filas con la misma referencia forman una compra) | cada fila es una compra |
| **fecha** | Fecha de recepción (o de pedido si está pendiente) | |
| proveedor | Proveedor | Sin proveedor |
| **sku**, **cantidad**, **coste_unitario** (+ moneda) | Qué entró y a qué coste | |
| estado | recibida / pendiente / cancelada | recibida |

**`inventario`** — conteos de existencias. Muy recomendable: sin al menos uno, el stock se deduce solo de compras y ventas.

| Columna | Qué es | Por defecto |
|---|---|---|
| **sku**, **stock** | Existencias contadas | |
| fecha | Momento del conteo (solo fecha = al cierre de ese día) | ahora |
| coste_medio_usd | Coste medio en ese momento | — |

**`devoluciones`**: **numero** (ticket), **sku**, **fecha**, **cantidad**, reembolso + moneda (por defecto, lo que
se cobró), motivo, reingresa_stock (sí / no, por defecto sí).

**`tasas`**: **fecha**, **usd_cup**. Tasa del mercado informal de cada día. Si falta un día se usa la anterior. Con
`ELTOQUE_API_KEY` y la opción `--eltoque`, el importador descarga de elTOQUE las que falten.

**`precios`** (historial, opcional): **sku**, precio + moneda, **desde**. El precio del catálogo es el actual.

**`categorias`** (opcional): **categoria**, linea (Mercado / Envíos), plazo_dias (reposición), dias_stock_minimo, basico
(sí / no: los básicos siempre son prioritarios en las alertas). Por defecto: Mercado, 7, 7, no.

## 3. Validar e importar

```bash
python -m agente_interno.importador validar datos/importar     # no escribe nada
python -m agente_interno.importador importar datos/importar    # reconstruye los datos del negocio
```

Las dos órdenes muestran un resumen, los **avisos** (agrupados, con ejemplos) y los **errores** con archivo y fila:

```
Resumen:
  · productos: 8 (8 activos)
  · ventas: 16 tickets (1 anulados), 23 líneas
  · periodo: 20/09/2026 – 04/10/2026 18:10
  ...
Avisos (1):
  ! Conteos que no cuadran con las ventas y compras (se ajusta el stock) (2): ARR-1KG 04/10 41→35, HUE-30 04/10 15→9
Errores (1 filas no se pueden importar):
  ✗ ventas.csv, fila 14: ticket T-1009: falta precio o importe
```

Si hay errores **no se importa nada**, salvo con `--omitir-errores` (se descartan esas filas). La importación es una sola
transacción: el agente sigue viendo los datos anteriores hasta que termina y nunca ve un estado a medias.

Opciones: `--negocio "Nombre"` (o `NEGOCIO_NOMBRE`; si la base tiene un solo negocio, se usa ese), `--eltoque`,
`--db` (en lugar de `DB_URL_IMPORTADOR`), `--ahora` (pruebas).

## 4. Cómo se calculan stock, costes y precios

- **Stock**: se recorren en orden cronológico compras recibidas, ventas, anulaciones, devoluciones que vuelven al stock
  y conteos. Antes del primer conteo, el stock se reconstruye hacia atrás desde ese conteo (*saldo inicial*): la
  historia queda coherente y nunca negativa. Después, cada conteo que no cuadra genera un ajuste (aparece en los avisos).
- **Coste medio**: ponderado con cada compra. El coste de cada venta es el coste medio del producto en ese momento
  (salvo que el archivo traiga `coste_unitario_usd`). Sin ningún coste conocido, el margen sale sobreestimado (aviso).
- **USD y CUP**: el sistema trabaja en USD. Los importes en CUP se convierten con la tasa de la venta (columna `tasa`)
  o con la del día. Las tasas que traen las ventas se guardan para los días sin tasa.
- **Precios**: el del catálogo es el vigente; el archivo `precios` aporta el historial. Sin precio en el catálogo se
  usa el de la última venta (aviso).
- **Productos**: se identifican por SKU y conservan su identidad entre importaciones. Un producto que deja de aparecer
  en los archivos queda **inactivo** (no se borra).

## 5. Actualización diaria

Basta con añadir a la carpeta los archivos nuevos (por ejemplo, `ventas_2026-10-05.csv` y un `inventario` de vez en
cuando) y repetir `importar`. Con un `cron` en el servidor:

```cron
# Cada día a las 19:00, antes del resumen diario de las 19:30
0 19 * * * cd /app && python -m agente_interno.importador importar /app/datos/importar >> /app/datos/importar.log 2>&1
```

Mientras el bot no reciba archivos directamente, los archivos llegan a la carpeta del servidor por SFTP/`scp` o por la
consola de Easypanel.

## Problemas frecuentes

| Mensaje | Qué hacer |
|---|---|
| `no hay tasa USD→CUP para el …` | Añade `tasas.csv`, una columna `tasa` en las ventas o usa `--eltoque` |
| `el nombre no indica qué contiene` | Renombra el archivo empezando por `productos`, `ventas`, `compras`… |
| `columnas no reconocidas` | Son columnas que no se usan; si alguna debería usarse, añádela a `mapeo.json` |
| `faltan las columnas …` | El archivo no tiene una columna obligatoria (o tiene otro nombre: usa `mapeo.json`) |
| `una transferencia se registra en CUP` | El esquema solo admite transferencias en CUP; corrige la moneda o el método |
| `permission denied` | `DB_URL_IMPORTADOR` no usa el rol `agente_importador`, o falta `instalar-esquema` |
