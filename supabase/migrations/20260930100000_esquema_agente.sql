-- Esquema `agente`: las 12 herramientas de solo lectura del Agente Interno.
-- Reglas: docs/especificacion/05_reglas_de_negocio.md · Contratos: 04_herramientas_input_output.md
-- Todas las funciones públicas reciben un único parámetro jsonb (validado aquí) y devuelven el sobre JSON común.

create schema if not exists extensions;
create extension if not exists pg_trgm with schema extensions;
create extension if not exists unaccent with schema extensions;

create schema if not exists agente;

-- Configuración ------------------------------------------------------------

create table agente.parametros (
  clave       text primary key,
  valor       numeric not null,
  descripcion text not null
);
insert into agente.parametros values
  ('velocidad_dias',            30,  'Días para calcular la velocidad de venta'),
  ('exceso_dias',               90,  'Cobertura a partir de la cual hay exceso de stock'),
  ('sin_movimiento_dias',       30,  'Días sin ventas con stock para "sin movimiento"'),
  ('baja_rotacion_pct',         25,  'Velocidad por debajo de este % de la media de su categoría'),
  ('agotado_demanda_dias',      60,  'Un agotado cuenta si vendió en estos días'),
  ('riesgo_min_velocidad',      0.2, 'Velocidad mínima (u/día) para alertar riesgo de rotura'),
  ('margen_minimo_pct',         10,  'Margen bruto mínimo aceptable'),
  ('margen_min_unidades',       10,  'Unidades mínimas vendidas en 30 días para evaluar margen'),
  ('devoluciones_pct',          5,   'Devoluciones sobre unidades vendidas en 30 días'),
  ('devoluciones_min_uds',      3,   'Unidades devueltas mínimas para alertar'),
  ('anulaciones_pct',           3,   'Anuladas sobre tickets de los últimos 7 días'),
  ('anulaciones_min_tickets',   100, 'Tickets mínimos para evaluar anulaciones'),
  ('caida_ventas_pct',          -30, 'Variación del día frente a lo esperado para alertar caída'),
  ('pico_ventas_pct',           30,  'Variación del día frente a lo esperado para alertar pico'),
  ('esperado_min_usd',          300, 'Ventas esperadas mínimas para evaluar caídas o picos'),
  ('hora_min_caida',            12,  'Hora local desde la que se evalúa la caída del día'),
  ('tasa_variacion_pct',        5,   'Variación de la tasa en 7 días para alertar'),
  ('frescura_max_min',          120, 'Minutos sin datos en horario de apertura para avisar'),
  ('abc_top_pct',               20,  '% de productos con más ingresos que son clase A'),
  ('abc_dias',                  90,  'Días de ingresos para la clasificación ABC'),
  ('compra_retraso_extra_dias', 7,   'Días extra sobre el plazo para considerar una compra retrasada'),
  ('max_rango_dias',            400, 'Rango máximo de fechas por consulta'),
  ('max_limit',                 50,  'Máximo de filas por lista');

create table agente.config_categoria (
  nombre            text primary key,          -- categoría o subcategoría
  linea             text not null check (linea in ('Mercado', 'Envíos')),
  plazo_dias        int  not null,
  dias_stock_minimo int  not null,
  basico            boolean not null default false
);
insert into agente.config_categoria values
  ('Alimentos',             'Mercado', 7, 7, false),
  ('Bebidas',               'Mercado', 7, 7, false),
  ('Combos',                'Mercado', 7, 7, false),
  ('Aseo e higiene',        'Mercado', 7, 7, true),
  ('Farmacia',              'Mercado', 7, 7, false),
  ('Ferretería',            'Mercado', 7, 7, false),
  ('Energía',               'Envíos', 21, 14, false),
  ('Climatización',         'Envíos', 21, 14, false),
  ('Electrodomésticos',     'Envíos', 21, 14, false),
  ('Electrónica',           'Envíos', 21, 14, false),
  ('Movilidad',             'Envíos', 21, 14, false),
  ('Cárnicos y congelados', 'Mercado', 7, 7, true),
  ('Granos y básicos',      'Mercado', 7, 7, true),
  ('Despensa y conservas',  'Mercado', 7, 7, true);

-- Utilidades -----------------------------------------------------------------

-- "Ahora" = hora real, salvo que la sesión fije agente.ahora (pruebas y modo demo con fecha fija).
create function agente._ahora() returns timestamptz language sql stable as $$
  select coalesce(nullif(current_setting('agente.ahora', true), '')::timestamptz, now())
$$;

create function agente._hoy() returns date language sql stable as $$
  select (agente._ahora() at time zone 'America/Havana')::date
$$;

create function agente._ts(d date) returns timestamptz language sql immutable as $$
  select d::timestamp at time zone 'America/Havana'
$$;

create function agente._neg() returns bigint language sql stable as $$
  select coalesce(nullif(current_setting('agente.negocio_id', true), '')::bigint, (select min(id) from public.negocios))
$$;

create function agente._p(k text) returns numeric language sql stable as $$
  select valor from agente.parametros where clave = k
$$;

create function agente._tasa(d date) returns numeric language sql stable as $$
  select usd_cup from public.tasas_cambio where fecha <= d order by fecha desc limit 1
$$;

create function agente._cup(usd numeric, tasa numeric) returns numeric language sql immutable as $$
  select ceil(usd * tasa / 10) * 10
$$;

create function agente._r(x numeric, n int default 2) returns numeric language sql immutable as $$
  select round(x, n)
$$;

create function agente._pct(a numeric, b numeric) returns numeric language sql immutable as $$
  select case when b is null or b = 0 then null else round((a - b) / abs(b) * 100, 1) end
$$;

-- ISO 8601 con el desplazamiento de La Habana (-04:00 / -05:00).
create function agente._iso(t timestamptz) returns text language sql immutable as $$
  select case when t is null then null else
    to_char(t at time zone 'America/Havana', 'YYYY-MM-DD"T"HH24:MI:SS')
    || case when extract(epoch from (t at time zone 'America/Havana') - (t at time zone 'UTC')) < 0 then '-' else '+' end
    || lpad(abs(extract(epoch from (t at time zone 'America/Havana') - (t at time zone 'UTC')) / 3600)::int::text, 2, '0')
    || ':00' end
$$;

create function agente._horas(t timestamptz) returns text language sql immutable as $$
  select to_char(t at time zone 'America/Havana', 'HH24:MI')
$$;

create function agente._norm(t text) returns text language sql stable as $$
  select lower(extensions.unaccent(coalesce(t, '')))
$$;

-- Errores de validación: se lanzan con SQLSTATE P0001 y el código en HINT.
create function agente._error(codigo text, mensaje text) returns void language plpgsql as $$
begin
  raise exception using errcode = 'P0001', message = mensaje, hint = codigo;
end $$;

-- Validación de parámetros -----------------------------------------------------

create function agente._claves(p jsonb, permitidas text[]) returns void language plpgsql as $$
declare k text;
begin
  if p is null then return; end if;
  if jsonb_typeof(p) <> 'object' then
    perform agente._error('invalid_params', 'Los parámetros deben ser un objeto.');
  end if;
  for k in select jsonb_object_keys(p) loop
    if not k = any (permitidas) then
      perform agente._error('invalid_params', format('Parámetro no reconocido: %s.', k));
    end if;
  end loop;
end $$;

create function agente._fecha(p jsonb, k text, def date) returns date language plpgsql as $$
declare v text := p ->> k;
begin
  if v is null or v = '' then return def; end if;
  if v !~ '^\d{4}-\d{2}-\d{2}$' then
    perform agente._error('invalid_params', format('La fecha "%s" debe tener el formato AAAA-MM-DD.', k));
  end if;
  return v::date;
exception when datetime_field_overflow or invalid_datetime_format then
  perform agente._error('invalid_params', format('La fecha "%s" no es válida.', k));
  return null;
end $$;

create function agente._enum(p jsonb, k text, permitidos text[], def text) returns text language plpgsql as $$
declare v text := p ->> k;
begin
  if v is null or v = '' then return def; end if;
  if not v = any (permitidos) then
    perform agente._error('invalid_params', format('"%s" debe ser uno de: %s.', k, array_to_string(permitidos, ', ')));
  end if;
  return v;
end $$;

create function agente._int(p jsonb, k text, def int, minimo int, maximo int) returns int language plpgsql as $$
declare v text := p ->> k; n int;
begin
  if v is null or v = '' then return def; end if;
  if v !~ '^-?\d+$' then perform agente._error('invalid_params', format('"%s" debe ser un número entero.', k)); end if;
  n := v::int;
  if n < minimo or n > maximo then
    perform agente._error('invalid_params', format('"%s" debe estar entre %s y %s.', k, minimo, maximo));
  end if;
  return n;
end $$;

create function agente._num(p jsonb, k text) returns numeric language plpgsql as $$
declare v text := p ->> k;
begin
  if v is null or v = '' then return null; end if;
  if v !~ '^-?\d+(\.\d+)?$' then perform agente._error('invalid_params', format('"%s" debe ser un número.', k)); end if;
  return v::numeric;
end $$;

create function agente._bool(p jsonb, k text, def boolean) returns boolean language plpgsql as $$
begin
  if not p ? k or p -> k = 'null'::jsonb then return def; end if;
  if jsonb_typeof(p -> k) <> 'boolean' then perform agente._error('invalid_params', format('"%s" debe ser true o false.', k)); end if;
  return (p ->> k)::boolean;
end $$;

create function agente._texto(p jsonb, k text, obligatorio boolean, minimo int, maximo int) returns text language plpgsql as $$
declare v text := btrim(p ->> k);
begin
  if v is null or v = '' then
    if obligatorio then perform agente._error('invalid_params', format('Falta el parámetro "%s".', k)); end if;
    return null;
  end if;
  if length(v) < minimo or length(v) > maximo then
    perform agente._error('invalid_params', format('"%s" debe tener entre %s y %s caracteres.', k, minimo, maximo));
  end if;
  return v;
end $$;

create function agente._rango(desde date, hasta date) returns void language plpgsql as $$
begin
  if desde is null or hasta is null then perform agente._error('invalid_params', 'Faltan las fechas "from" y "to".'); end if;
  if hasta < desde then perform agente._error('invalid_params', '"to" no puede ser anterior a "from".'); end if;
  if hasta - desde + 1 > agente._p('max_rango_dias') then
    perform agente._error('invalid_params', format('El rango máximo es de %s días.', agente._p('max_rango_dias')));
  end if;
end $$;

-- Fin exclusivo de un rango de fechas, sin pasar de "ahora".
create function agente._fin(hasta date) returns timestamptz language sql stable as $$
  select least(agente._ts(hasta + 1), agente._ahora())
$$;

-- Tienda física abierta en un instante (horario y festivos de 05_reglas_de_negocio.md §5.1).
create function agente._abierto(t timestamptz) returns boolean language sql stable as $$
  select case
    when to_char(t at time zone 'America/Havana', 'MM-DD') in ('01-01', '05-01', '07-25', '07-26', '07-27', '10-10', '12-25') then false
    when extract(isodow from t at time zone 'America/Havana') = 7
      then (t at time zone 'America/Havana')::time >= '09:00' and (t at time zone 'America/Havana')::time < '13:00'
    else (t at time zone 'America/Havana')::time >= '09:00' and (t at time zone 'America/Havana')::time < '19:00'
  end
$$;

-- Avisos generales que acompañan a todas las respuestas.
create function agente._avisos() returns text[] language plpgsql stable as $$
declare
  ahora timestamptz := agente._ahora();
  ultima timestamptz;
  a text[] := '{}';
  n int;
begin
  select max(fecha) into ultima from public.ventas where negocio_id = agente._neg() and fecha <= ahora;
  if agente._abierto(ahora) and (ultima is null or ahora - ultima > agente._p('frescura_max_min') * interval '1 minute') then
    a := a || format('Los últimos datos son de las %s; puede que falten ventas recientes.', agente._horas(ultima));
  end if;
  if not exists (select 1 from public.tasas_cambio where fecha = agente._hoy()) then
    a := a || format('No hay tasa de hoy; se usa la del %s.',
                     (select to_char(max(fecha), 'DD/MM') from public.tasas_cambio where fecha <= agente._hoy()));
  end if;
  select count(*) into n from public.productos p
  where p.negocio_id = agente._neg() and p.activo
    and not exists (select 1 from public.precios_producto pr where pr.producto_id = p.id
                    and pr.vigente_desde <= ahora and (pr.vigente_hasta is null or pr.vigente_hasta > ahora));
  if n > 0 then a := a || format('%s producto(s) activo(s) sin precio: no se pueden vender.', n); end if;
  return a;
end $$;

-- Sobre común de salida (04 §4.1).
create function agente._sobre(herramienta text, params jsonb, desde date, hasta date, datos jsonb,
                              calculos text[], hechos text[]) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'status', case when datos is null then 'no_data' else 'ok' end,
    'tool', herramienta,
    'params', coalesce(params, '{}'::jsonb),
    'period', case when desde is null then null
                   else jsonb_build_object('from', desde, 'to', hasta, 'timezone', 'America/Havana') end,
    'data_as_of', agente._iso((select max(fecha) from public.ventas where negocio_id = agente._neg() and fecha <= agente._ahora())),
    'generated_at', agente._iso(agente._ahora()),
    'fx', jsonb_build_object('date', (select max(fecha) from public.tasas_cambio where fecha <= agente._hoy()),
                             'usd_cup', agente._tasa(agente._hoy()), 'source', 'elTOQUE'),
    'data', datos,
    'kinds', jsonb_build_object('fact', to_jsonb(coalesce(hechos, '{}')), 'calculation', to_jsonb(coalesce(calculos, '{}'))),
    'warnings', to_jsonb(agente._avisos()))
$$;

create function agente._fallo(herramienta text, estado text, mensaje text, codigo text) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'status', 'error',
    'tool', herramienta,
    'error_code', case when estado = 'P0001' and codigo in ('invalid_params', 'not_found', 'ambiguous') then codigo else 'internal' end,
    'message', case when estado = 'P0001' then mensaje else 'No se pudo completar la consulta.' end,
    'generated_at', agente._iso(agente._ahora()))
$$;

-- Clave de agrupación de una serie.
create function agente._clave(agrupar text, t timestamptz, canal text, categoria text) returns text language sql immutable as $$
  select case agrupar
    when 'none' then 'total'
    when 'day' then to_char((t at time zone 'America/Havana')::date, 'YYYY-MM-DD')
    when 'week' then to_char(date_trunc('week', t at time zone 'America/Havana')::date, 'YYYY-MM-DD')
    when 'month' then to_char(t at time zone 'America/Havana', 'YYYY-MM')
    when 'channel' then canal
    when 'category' then categoria
  end
$$;

-- Ventas del periodo [desde, hasta) agrupadas (definiciones de 05 §5.3).
create function agente._serie(p_desde timestamptz, p_hasta timestamptz, p_canal text, p_agrupar text)
returns table (clave text, bruto_usd numeric, bruto_cup numeric, devol_usd numeric, devol_cup numeric,
               coste numeric, tickets bigint, unidades numeric, anuladas bigint)
language sql stable as $$
  with l as (
    select agente._clave(p_agrupar, v.fecha, v.canal, pc.nombre) as k, v.id as vid,
           lv.cantidad as c, lv.cantidad * lv.precio_unitario_usd as u, lv.cantidad * lv.precio_unitario_cup as cu,
           lv.cantidad * lv.coste_unitario_usd as co
    from public.ventas v
    join public.lineas_venta lv on lv.venta_id = v.id
    join public.productos p on p.id = lv.producto_id
    join public.categorias sc on sc.id = p.categoria_id
    join public.categorias pc on pc.id = sc.categoria_padre_id
    where v.negocio_id = agente._neg() and v.estado = 'completada'
      and v.fecha >= p_desde and v.fecha < p_hasta and (p_canal = 'all' or v.canal = p_canal)
  ), la as (
    select k, sum(u) u, sum(cu) cu, sum(co) co, count(distinct vid) t, sum(c) c from l group by k
  ), r as (
    select agente._clave(p_agrupar, d.fecha, v.canal, pc.nombre) as k,
           sum(d.reembolso_usd) ru, sum(d.cantidad * lv.precio_unitario_cup) rc,
           sum(case when d.reingresa_stock then d.cantidad * lv.coste_unitario_usd else 0 end) rco
    from public.devoluciones d
    join public.lineas_venta lv on lv.id = d.linea_venta_id
    join public.ventas v on v.id = lv.venta_id
    join public.productos p on p.id = lv.producto_id
    join public.categorias sc on sc.id = p.categoria_id
    join public.categorias pc on pc.id = sc.categoria_padre_id
    where v.negocio_id = agente._neg() and d.fecha >= p_desde and d.fecha < p_hasta and (p_canal = 'all' or v.canal = p_canal)
    group by 1
  ), an as (
    select agente._clave(p_agrupar, v.fecha, v.canal, null) as k, count(*) n
    from public.ventas v
    where p_agrupar <> 'category' and v.negocio_id = agente._neg() and v.estado = 'anulada'
      and v.fecha >= p_desde and v.fecha < p_hasta and (p_canal = 'all' or v.canal = p_canal)
    group by 1
  ), ks as (
    select k from la union select k from r union select k from an
    union select 'total' where p_agrupar = 'none'
  )
  select ks.k,
         coalesce(la.u, 0), coalesce(la.cu, 0), coalesce(r.ru, 0), coalesce(r.rc, 0),
         coalesce(la.co, 0) - coalesce(r.rco, 0),
         coalesce(la.t, 0), coalesce(la.c, 0), coalesce(an.n, 0)
  from ks left join la on la.k = ks.k left join r on r.k = ks.k left join an on an.k = ks.k
  order by ks.k
$$;

-- Totales en JSON a partir de una fila de _serie.
create function agente._totales_json(bruto_usd numeric, bruto_cup numeric, devol_usd numeric, devol_cup numeric,
                                     coste numeric, tickets bigint, unidades numeric, anuladas bigint)
returns jsonb language sql immutable as $$
  select jsonb_build_object(
    'gross_usd', round(bruto_usd, 2),
    'returns_usd', round(devol_usd, 2),
    'net_usd', round(bruto_usd - devol_usd, 2),
    'net_cup', round(bruto_cup - devol_cup, 0),
    'tickets', tickets,
    'units', round(unidades, 0),
    'avg_ticket_usd', case when tickets > 0 then round(bruto_usd / tickets, 2) end,
    'cogs_usd', round(coste, 2),
    'gross_profit_usd', round(bruto_usd - devol_usd - coste, 2),
    'gross_margin_pct', case when bruto_usd - devol_usd > 0
                             then round((bruto_usd - devol_usd - coste) / (bruto_usd - devol_usd) * 100, 1) end,
    'voided_tickets', anuladas)
$$;

create function agente._totales(desde timestamptz, hasta timestamptz, canal text) returns jsonb language sql stable as $$
  select agente._totales_json(bruto_usd, bruto_cup, devol_usd, devol_cup, coste, tickets, unidades, anuladas)
  from agente._serie(desde, hasta, canal, 'none')
$$;

-- Métricas por producto en el instante actual (05 §5.4 y §5.5).
create function agente._productos()
returns table (producto_id bigint, sku text, nombre text, categoria text, subcategoria text, linea text,
               plazo_dias int, basico boolean, activo boolean, dias_alta int, stock numeric, stock_minimo numeric,
               coste_medio numeric, precio_usd numeric, uds_30d numeric, net_usd_30d numeric, coste_30d numeric,
               uds_60d numeric, net_usd_90d numeric, velocidad numeric, cobertura numeric, ultima_venta timestamptz,
               pendiente numeric, abc text, prioritario boolean, estado text, dias_sin_stock int,
               devueltas_30d numeric, margen_30d numeric, baja_rotacion boolean, valor_stock numeric)
language sql stable as $$
  with a as (select agente._ahora() ahora, agente._hoy() hoy),
  base as (
    select p.id, p.sku, p.nombre, pc.nombre cat, sc.nombre subcat, cc.linea, cc.plazo_dias,
           (cc.basico or coalesce(cs.basico, false)) basico, p.activo,
           (a.hoy - (p.creado_en at time zone 'America/Havana')::date) dias_alta,
           i.stock_actual, p.stock_minimo, i.coste_medio_usd,
           (select pr.precio_usd from public.precios_producto pr
             where pr.producto_id = p.id and pr.vigente_desde <= a.ahora
               and (pr.vigente_hasta is null or pr.vigente_hasta > a.ahora)
             order by pr.vigente_desde desc limit 1) precio
    from public.productos p
    cross join a
    join public.categorias sc on sc.id = p.categoria_id
    join public.categorias pc on pc.id = sc.categoria_padre_id
    join agente.config_categoria cc on cc.nombre = pc.nombre
    left join agente.config_categoria cs on cs.nombre = sc.nombre
    join public.inventario i on i.producto_id = p.id
    where p.negocio_id = agente._neg()
  ),
  ventas as (
    select lv.producto_id,
           sum(lv.cantidad) filter (where v.fecha > a.ahora - interval '30 days') u30,
           sum(lv.cantidad * lv.precio_unitario_usd) filter (where v.fecha > a.ahora - interval '30 days') r30,
           sum(lv.cantidad * lv.coste_unitario_usd) filter (where v.fecha > a.ahora - interval '30 days') c30,
           sum(lv.cantidad) filter (where v.fecha > a.ahora - agente._p('agotado_demanda_dias') * interval '1 day') u60,
           sum(lv.cantidad * lv.precio_unitario_usd) r90
    from public.lineas_venta lv
    join public.ventas v on v.id = lv.venta_id
    cross join a
    where v.negocio_id = agente._neg() and v.estado = 'completada'
      and v.fecha > a.ahora - agente._p('abc_dias') * interval '1 day' and v.fecha <= a.ahora
    group by 1
  ),
  devol as (
    select lv.producto_id,
           sum(d.cantidad) filter (where d.fecha > a.ahora - interval '30 days') d30,
           sum(d.reembolso_usd) filter (where d.fecha > a.ahora - interval '30 days') dr30,
           sum(case when d.reingresa_stock then d.cantidad * lv.coste_unitario_usd else 0 end)
             filter (where d.fecha > a.ahora - interval '30 days') dc30,
           sum(d.reembolso_usd) dr90
    from public.devoluciones d
    join public.lineas_venta lv on lv.id = d.linea_venta_id
    cross join a
    where d.fecha > a.ahora - agente._p('abc_dias') * interval '1 day' and d.fecha <= a.ahora
    group by 1
  ),
  ultima as (
    select lv.producto_id, max(v.fecha) f
    from public.lineas_venta lv join public.ventas v on v.id = lv.venta_id cross join a
    where v.estado = 'completada' and v.fecha <= a.ahora and v.negocio_id = agente._neg()
    group by 1
  ),
  ultimo_mov as (
    select m.producto_id, max(m.fecha) f from public.movimientos_inventario m cross join a
    where m.fecha <= a.ahora group by 1
  ),
  pend as (
    select lc.producto_id, sum(lc.cantidad) q
    from public.lineas_compra lc join public.compras c on c.id = lc.compra_id
    where c.estado = 'pendiente' and c.negocio_id = agente._neg()
    group by 1
  ),
  m as (
    select b.*, coalesce(v.u30, 0) u30, coalesce(v.r30, 0) - coalesce(d.dr30, 0) n30,
           coalesce(v.c30, 0) - coalesce(d.dc30, 0) c30, coalesce(v.u60, 0) u60,
           coalesce(v.r90, 0) - coalesce(d.dr90, 0) n90, coalesce(d.d30, 0) d30,
           coalesce(v.u30, 0) / agente._p('velocidad_dias') vel,
           u.f ultima, coalesce(pe.q, 0) pendiente, um.f ultimo_mov
    from base b
    left join ventas v on v.producto_id = b.id
    left join devol d on d.producto_id = b.id
    left join ultima u on u.producto_id = b.id
    left join ultimo_mov um on um.producto_id = b.id
    left join pend pe on pe.producto_id = b.id
  ),
  abc as (
    select id, row_number() over (order by n90 desc) rn, count(*) over () total
    from m where activo and n90 > 0
  ),
  catvel as (
    select cat, avg(vel) vmedia from m where activo and dias_alta >= 30 group by cat
  )
  select m.id, m.sku, m.nombre, m.cat, m.subcat, m.linea, m.plazo_dias, m.basico, m.activo, m.dias_alta,
         m.stock_actual, m.stock_minimo, m.coste_medio_usd, m.precio,
         m.u30, round(m.n30, 2), round(m.c30, 2), m.u60, round(m.n90, 2),
         round(m.vel, 2),
         case when m.vel > 0 then round(m.stock_actual / m.vel, 1) end,
         m.ultima, m.pendiente,
         case when abc.rn <= ceil((select count(*) from m m2 where m2.activo) * agente._p('abc_top_pct') / 100.0) then 'A'
              when abc.rn <= ceil((select count(*) from m m2 where m2.activo) * 0.5) then 'B'
              else 'C' end,
         m.activo and (m.basico or abc.rn <= ceil((select count(*) from m m2 where m2.activo) * agente._p('abc_top_pct') / 100.0)),
         case
           when not m.activo then 'inactivo'
           when m.stock_actual <= 0 and m.u60 > 0 then 'agotado'
           when m.stock_actual <= 0 then 'agotado_sin_demanda'
           when m.vel >= agente._p('riesgo_min_velocidad')
                and (m.stock_actual + m.pendiente) / m.vel < m.plazo_dias then 'riesgo_rotura'
           when m.stock_actual <= m.stock_minimo then 'stock_bajo'
           when m.vel > 0 and m.stock_actual / m.vel > agente._p('exceso_dias') then 'exceso'
           when m.u30 = 0 and m.dias_alta >= agente._p('sin_movimiento_dias') then 'sin_movimiento'
           else 'normal'
         end,
         case when m.stock_actual <= 0 then ((select hoy from a) - (m.ultimo_mov at time zone 'America/Havana')::date) end,
         m.d30,
         case when m.n30 > 0 then round((m.n30 - m.c30) / m.n30 * 100, 1) end,
         m.activo and m.dias_alta >= 30 and cv.vmedia > 0 and m.vel < cv.vmedia * agente._p('baja_rotacion_pct') / 100,
         round(m.stock_actual * m.coste_medio_usd, 2)
  from m
  left join abc on abc.id = m.id
  left join catvel cv on cv.cat = m.cat
$$;

-- Ventas del día hasta "hasta" frente a lo esperado (media de los 4 mismos días de la semana anteriores).
create function agente._dia_vs_esperado(d date)
returns table (net_hoy numeric, tickets_hoy bigint, net_esperado numeric, tickets_esperado numeric, variacion_pct numeric, hasta timestamptz)
language sql stable as $$
  with h as (select least(agente._ts(d + 1), agente._ahora()) hasta),
  hoy as (
    select bruto_usd - devol_usd net, tickets from h, agente._serie(agente._ts(d), h.hasta, 'all', 'none')
  ),
  prev as (
    select avg(s.bruto_usd - s.devol_usd) net, avg(s.tickets) t
    from h, generate_series(1, 4) k,
         agente._serie(agente._ts(d - 7 * k), agente._ts(d - 7 * k) + (h.hasta - agente._ts(d)), 'all', 'none') s
  )
  select round(hoy.net, 2), hoy.tickets, round(prev.net, 2), round(prev.t, 1), agente._pct(hoy.net, prev.net), h.hasta
  from hoy, prev, h
$$;
