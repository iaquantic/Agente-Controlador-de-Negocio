-- Esquema inicial de MercadoMVP (fase 2 validada).
-- Importes USD en numeric(12,2); CUP en numeric(14,2); costes unitarios medios en numeric(12,4).
-- Timestamps en UTC (timestamptz); los informes se muestran en America/Havana.

create table negocios (
  id                bigint generated always as identity primary key,
  nombre            text not null unique,
  zona_horaria      text not null default 'America/Havana',
  moneda_referencia text not null default 'USD' check (moneda_referencia in ('USD', 'CUP')),
  creado_en         timestamptz not null default now()
);

create table categorias (
  id                 bigint generated always as identity primary key,
  negocio_id         bigint not null references negocios (id),
  nombre             text not null,
  categoria_padre_id bigint references categorias (id),
  unique nulls not distinct (negocio_id, categoria_padre_id, nombre)
);

create table productos (
  id           bigint generated always as identity primary key,
  negocio_id   bigint not null references negocios (id),
  sku          text not null,
  nombre       text not null,
  categoria_id bigint not null references categorias (id),
  unidad       text not null default 'unidad',
  stock_minimo numeric(12,3) not null default 0 check (stock_minimo >= 0),
  activo       boolean not null default true,
  creado_en    timestamptz not null default now(),
  unique (negocio_id, sku)
);

create table precios_producto (
  id            bigint generated always as identity primary key,
  producto_id   bigint not null references productos (id),
  precio_usd    numeric(12,2) not null check (precio_usd > 0),
  vigente_desde timestamptz not null,
  vigente_hasta timestamptz,
  check (vigente_hasta is null or vigente_hasta > vigente_desde)
);
-- Un único precio vigente por producto.
create unique index precios_producto_vigente_uq on precios_producto (producto_id) where vigente_hasta is null;

create table proveedores (
  id         bigint generated always as identity primary key,
  negocio_id bigint not null references negocios (id),
  nombre     text not null,
  activo     boolean not null default true,
  unique (negocio_id, nombre)
);

create table compras (
  id           bigint generated always as identity primary key,
  negocio_id   bigint not null references negocios (id),
  proveedor_id bigint not null references proveedores (id),
  fecha        timestamptz not null,
  estado       text not null check (estado in ('pendiente', 'recibida', 'cancelada')),
  total_usd    numeric(12,2) not null default 0 check (total_usd >= 0)
);

create table lineas_compra (
  id                 bigint generated always as identity primary key,
  compra_id          bigint not null references compras (id),
  producto_id        bigint not null references productos (id),
  cantidad           numeric(12,3) not null check (cantidad > 0),
  coste_unitario_usd numeric(12,2) not null check (coste_unitario_usd >= 0)
);

create table inventario (
  producto_id     bigint primary key references productos (id),
  stock_actual    numeric(12,3) not null default 0 check (stock_actual >= 0),
  coste_medio_usd numeric(12,4) not null default 0 check (coste_medio_usd >= 0),
  actualizado_en  timestamptz not null default now()
);

create table movimientos_inventario (
  id              bigint generated always as identity primary key,
  producto_id     bigint not null references productos (id),
  fecha           timestamptz not null,
  tipo            text not null check (tipo in ('compra', 'venta', 'devolucion', 'anulacion_venta',
                                                'ajuste_positivo', 'ajuste_negativo', 'merma')),
  cantidad        numeric(12,3) not null check (cantidad <> 0),
  referencia_tipo text check (referencia_tipo in ('compra', 'venta', 'devolucion', 'ajuste')),
  referencia_id   bigint,
  -- Entradas positivas, salidas negativas.
  check (
    (tipo in ('compra', 'devolucion', 'anulacion_venta', 'ajuste_positivo') and cantidad > 0)
    or (tipo in ('venta', 'ajuste_negativo', 'merma') and cantidad < 0)
  )
);

create table tasas_cambio (
  fecha       date primary key,
  usd_cup     numeric(10,2) not null check (usd_cup > 0),
  fuente      text not null default 'elTOQUE',
  obtenida_en timestamptz not null default now()
);

create table ventas (
  id               bigint generated always as identity primary key,
  negocio_id       bigint not null references negocios (id),
  numero           text not null,
  canal            text not null check (canal in ('tienda_fisica', 'web')),
  fecha            timestamptz not null,
  estado           text not null check (estado in ('completada', 'anulada')),
  tasa_usd_cup     numeric(10,2) not null check (tasa_usd_cup > 0),
  total_usd        numeric(12,2) not null check (total_usd >= 0),
  total_cup        numeric(14,2) not null check (total_cup >= 0),
  anulada_en       timestamptz,
  motivo_anulacion text,
  unique (negocio_id, numero),
  check ((estado = 'anulada') = (anulada_en is not null))
);

create table lineas_venta (
  id                  bigint generated always as identity primary key,
  venta_id            bigint not null references ventas (id),
  producto_id         bigint not null references productos (id),
  cantidad            numeric(12,3) not null check (cantidad > 0),
  precio_unitario_usd numeric(12,2) not null check (precio_unitario_usd >= 0),
  precio_unitario_cup numeric(14,2) not null check (precio_unitario_cup >= 0),
  coste_unitario_usd  numeric(12,4) not null check (coste_unitario_usd >= 0)
);

create table pagos (
  id       bigint generated always as identity primary key,
  venta_id bigint not null references ventas (id),
  moneda   text not null check (moneda in ('USD', 'CUP')),
  metodo   text not null check (metodo in ('efectivo', 'transferencia')),
  importe  numeric(14,2) not null check (importe > 0),
  check (not (metodo = 'transferencia' and moneda = 'USD'))
);

create table devoluciones (
  id              bigint generated always as identity primary key,
  linea_venta_id  bigint not null references lineas_venta (id),
  fecha           timestamptz not null,
  cantidad        numeric(12,3) not null check (cantidad > 0),
  motivo          text,
  reembolso_usd   numeric(12,2) not null default 0 check (reembolso_usd >= 0),
  reingresa_stock boolean not null default true
);

-- Índices para claves foráneas y consultas por fecha.
create index on categorias (negocio_id);
create index on categorias (categoria_padre_id);
create index on productos (categoria_id);
create index on proveedores (negocio_id);
create index on compras (negocio_id, fecha);
create index on compras (proveedor_id);
create index on lineas_compra (compra_id);
create index on lineas_compra (producto_id);
create index on movimientos_inventario (producto_id, fecha);
create index on ventas (negocio_id, fecha);
create index on lineas_venta (venta_id);
create index on lineas_venta (producto_id);
create index on pagos (venta_id);
create index on devoluciones (linea_venta_id);

-- RLS activado sin políticas: la API pública (anon/authenticated) no puede leer ni escribir.
-- El acceso de solo lectura del agente se definirá en la fase 5.
alter table negocios               enable row level security;
alter table categorias             enable row level security;
alter table productos              enable row level security;
alter table precios_producto       enable row level security;
alter table proveedores            enable row level security;
alter table compras                enable row level security;
alter table lineas_compra          enable row level security;
alter table inventario             enable row level security;
alter table movimientos_inventario enable row level security;
alter table tasas_cambio           enable row level security;
alter table ventas                 enable row level security;
alter table lineas_venta           enable row level security;
alter table pagos                  enable row level security;
alter table devoluciones           enable row level security;
