-- Generador del historial de demostración de MercadoAgentico.
-- Vive en el esquema temporal `gen`, que se elimina al terminar (el agente nunca lo ve).
-- Requiere: esquema public creado (migración inicial), gen.catalogo cargado y tasas_cambio cargada.
-- Orden: gen.preparar() -> gen.simular_rango(...) por tramos -> gen.finalizar() -> drop schema gen cascade.

create schema if not exists gen;

create table if not exists gen.catalogo (
  sku text primary key, nombre text, linea text, categoria text, subcategoria text,
  precio_usd numeric, demanda_dia numeric, perfil text, proveedor text
);

-- Situaciones sembradas para probar al agente.
create table gen.escenario (
  sku                  text primary key,
  sin_reposicion_desde date,     -- el proveedor deja de servir -> agotado
  demanda_cero_desde   date,     -- deja de venderse -> sin movimiento
  descatalogado_desde  date,     -- producto retirado (activo = false al final)
  coste_factor         numeric,  -- subida de coste sin subir precio -> margen bajo
  coste_factor_desde   date,
  devolucion_prob      numeric,  -- devoluciones anómalas
  devolucion_desde     date,
  sin_precio           boolean not null default false,
  alta                 date
);
insert into gen.escenario (sku, sin_reposicion_desde, demanda_cero_desde, descatalogado_desde,
                           coste_factor, coste_factor_desde, devolucion_prob, devolucion_desde, sin_precio, alta) values
  ('GRA-010', '2026-08-10', null, null, null, null, null, null, false, null),          -- aceite 1 L agotado
  ('GRA-012', '2026-08-25', null, null, null, null, null, null, false, null),          -- leche en polvo agotada
  ('ENE-009', '2026-08-01', null, null, null, null, null, null, false, null),          -- ventilador recargable agotado
  ('ENE-004', '2026-07-25', null, null, null, null, null, null, false, null),          -- estación 300 Wh agotada (compra pendiente)
  ('ELE-003', null, '2026-08-05', null, null, null, null, null, false, null),          -- freidora de aire sin movimiento
  ('ELE-011', null, '2026-08-10', null, null, null, null, null, false, null),          -- batidora sin movimiento
  ('MOV-003', null, '2026-07-01', null, null, null, null, null, false, null),          -- triciclo sin movimiento
  ('TEC-005', null, null, '2026-06-01', null, null, null, null, false, null),          -- descatalogados
  ('ELE-014', null, null, '2026-06-01', null, null, null, null, false, null),
  ('BEB-010', null, null, '2026-06-01', null, null, null, null, false, null),
  ('GRA-014', null, null, null, 1.22, '2026-07-01', null, null, false, null),          -- huevos: margen comprimido
  ('GRA-013', null, null, null, 1.24, '2026-08-01', null, null, false, null),          -- café: margen comprimido
  ('ELE-002', null, null, null, null, null, 0.25, '2026-08-15', false, null),          -- olla de presión: devoluciones
  ('ASE-016', null, null, null, null, null, null, null, true, '2026-09-26');           -- producto nuevo sin precio

-- Compras puntuales: excesos de stock, temporadas y reposiciones pendientes.
create table gen.compras_especiales (sku text, fecha date, cantidad int, plazo int);
insert into gen.compras_especiales values
  ('CLI-004', '2026-08-20',  50,  3),   -- aire split 1 ton: exceso tras el verano
  ('TEC-002', '2026-07-08',  45,  3),   -- TV 43": exceso
  ('CLI-001', '2026-08-28', 320,  3),   -- ventilador de pedestal: exceso
  ('FER-010', '2026-06-10', 130,  3),   -- pintura: exceso
  ('ELE-003', '2026-07-20',  12,  3),   -- freidora: stock que luego no se vende
  ('ELE-011', '2026-07-25',  10,  3),
  ('MOV-003', '2026-06-15',   3,  5),
  ('COM-007', '2026-04-24', 120,  2),   -- combo Día de las Madres
  ('COM-008', '2025-12-04',  90,  2),   -- combo fin de año
  ('ENE-004', '2026-09-24',  12, 20),   -- llega después de hoy: compra pendiente
  ('ASE-016', '2026-09-26',  24,  1);   -- producto nuevo sin precio

create table gen.producto_param (
  producto_id bigint primary key, sku text, linea text, categoria text, perfil text,
  demanda numeric, margen numeric, coste_base numeric, plazo_min int, plazo_max int,
  cobertura int, cuota_web numeric, proveedor_id bigint, r_precio numeric
);
create table gen.llegadas (compra_id bigint primary key, fecha_llegada date, especial boolean);
create table gen.devoluciones_pendientes (
  linea_venta_id bigint, venta_id bigint, producto_id bigint, fecha timestamptz, cantidad numeric,
  motivo text, reembolso numeric, reingresa boolean
);
create unlogged table gen.tmp_lineas (canal text, producto_id bigint, cantidad int, precio_usd numeric, orden float);
create unlogged table gen.tmp_pedido (producto_id bigint, proveedor_id bigint, cantidad int, plazo int);

-- Utilidades ---------------------------------------------------------------

create function gen.rnd() returns numeric language sql volatile as $$ select random()::numeric $$;

create function gen.ts(d date, horas numeric) returns timestamptz language sql immutable as $$
  select (d::timestamp + horas * interval '1 hour') at time zone 'America/Havana'
$$;

create function gen.poisson(lam numeric) returns int language plpgsql as $$
declare l float; k int := 0; p float := 1;
begin
  if lam is null or lam <= 0 then return 0; end if;
  if lam > 30 then
    return greatest(0, round(lam + sqrt(lam) * sqrt(-2 * ln(1 - gen.rnd())) * cos(2 * pi() * gen.rnd())));
  end if;
  l := exp(-lam);
  loop
    p := p * gen.rnd();
    exit when p <= l;
    k := k + 1;
  end loop;
  return k;
end $$;

create function gen.estacional(perfil text, d date) returns numeric language sql immutable as $$
  select case perfil
    when 'verano' then case extract(month from d)::int
      when 6 then 2.2 when 7 then 2.2 when 8 then 2.2 when 9 then 1.6 when 5 then 1.3
      when 10 then 0.9 when 4 then 0.8 when 11 then 0.5 when 3 then 0.5 else 0.35 end
    when 'verano_suave' then case when extract(month from d) between 6 and 9 then 1.3
      when extract(month from d) in (12, 1, 2) then 0.85 else 1 end
    when 'energia' then case when extract(month from d) in (9, 10) then 1.25 else 1 end
    when 'energia_verano' then case when extract(month from d) between 6 and 9 then 1.5
      when extract(month from d) = 10 then 1.2 else 1 end
    when 'fiestas' then case extract(month from d)::int when 12 then 1.7 when 7 then 1.3 else 1 end
    when 'madres' then case when d between make_date(extract(year from d)::int, 4, 28)
                                     and make_date(extract(year from d)::int, 5, 10) then 12 else 0 end
    when 'fin_ano' then case when extract(month from d) = 12 and extract(day from d) >= 10 then 4 else 0 end
    when 'dengue' then case when extract(month from d) in (9, 10, 11) then 2.2
      when extract(month from d) = 8 then 1.4 else 1 end
    else 1 end
$$;

-- Coste de compra en USD: inflación suave anual + subida sembrada + ruido.
create function gen.coste(pid bigint, d date) returns numeric language sql volatile as $$
  select round(pp.coste_base
    * case when pp.linea = 'Mercado' then 0.94 + 0.06 * (d - date '2025-10-01') / 365.0
           else 0.96 + 0.04 * (d - date '2025-10-01') / 365.0 end
    * case when e.coste_factor_desde is not null and d >= e.coste_factor_desde then e.coste_factor else 1 end
    * (0.97 + gen.rnd() * 0.06), 2)
  from gen.producto_param pp left join gen.escenario e using (sku)
  where pp.producto_id = pid
$$;

-- Preparación: negocio, catálogo, precios y compra inicial ---------------

create function gen.preparar() returns void language plpgsql as $$
declare neg bigint; s record; cid bigint;
begin
  perform setseed(0.2025);
  insert into negocios (nombre) values ('MercadoAgentico') returning id into neg;

  insert into categorias (negocio_id, nombre)
    select distinct neg, categoria from gen.catalogo;
  insert into categorias (negocio_id, nombre, categoria_padre_id)
    select distinct neg, c.subcategoria, pc.id
    from gen.catalogo c join categorias pc on pc.nombre = c.categoria and pc.categoria_padre_id is null;

  insert into proveedores (negocio_id, nombre) select distinct neg, proveedor from gen.catalogo;

  insert into productos (negocio_id, sku, nombre, categoria_id, stock_minimo, creado_en)
    select neg, c.sku, c.nombre, sc.id,
           ceil(c.demanda_dia * case when c.linea = 'Mercado' then 7 else 14 end),
           coalesce(gen.ts(e.alta, 11), gen.ts(date '2025-09-01', 9))
    from gen.catalogo c
    join categorias pc on pc.nombre = c.categoria and pc.categoria_padre_id is null
    join categorias sc on sc.nombre = c.subcategoria and sc.categoria_padre_id = pc.id
    left join gen.escenario e using (sku)
    order by c.sku;

  insert into gen.producto_param
    select p.id, c.sku, c.linea, c.categoria, c.perfil, c.demanda_dia, m.margen,
           round(c.precio_usd * (1 - m.margen), 4),
           case when c.linea = 'Mercado' then 2 else 12 end,
           case when c.linea = 'Mercado' then 6 else 21 end,
           case when c.linea = 'Mercado' then 30 else 45 end,
           case when c.linea = 'Mercado' then 0.25 else 0.40 end,
           pr.id, gen.rnd()
    from gen.catalogo c
    join productos p using (sku)
    join proveedores pr on pr.nombre = c.proveedor
    cross join lateral (
      select case c.categoria
               when 'Aseo e higiene' then 0.25 when 'Farmacia' then 0.30 when 'Ferretería' then 0.30
               when 'Alimentos' then 0.15 when 'Bebidas' then 0.15 when 'Combos' then 0.15
               else 0.20 end + gen.rnd() * 0.10 + 0 * c.precio_usd as margen
    ) m;
  -- Margen base fijo para los productos con subida de coste sembrada.
  update gen.producto_param pp set margen = 0.20, coste_base = round(c.precio_usd * 0.80, 4)
    from gen.catalogo c, gen.escenario e
    where c.sku = pp.sku and e.sku = pp.sku and e.coste_factor is not null;

  -- Precios: la mitad de los productos sube ~7 % en marzo o junio de 2026.
  insert into precios_producto (producto_id, precio_usd, vigente_desde, vigente_hasta)
    select pp.producto_id,
           case when cambia then round(c.precio_usd * 0.93, 2) else c.precio_usd end,
           gen.ts(date '2025-09-01', 0),
           case when cambia and pp.r_precio < 0.25 then gen.ts(date '2026-03-01', 0)
                when cambia then gen.ts(date '2026-06-01', 0)
                when e.descatalogado_desde is not null then gen.ts(e.descatalogado_desde, 0) end
    from gen.producto_param pp
    join gen.catalogo c using (sku)
    left join gen.escenario e using (sku)
    cross join lateral (
      select pp.r_precio < 0.5 and e.sku is null as cambia
    ) x
    where not coalesce(e.sin_precio, false);
  insert into precios_producto (producto_id, precio_usd, vigente_desde)
    select pp.producto_id, c.precio_usd,
           case when pp.r_precio < 0.25 then gen.ts(date '2026-03-01', 0) else gen.ts(date '2026-06-01', 0) end
    from gen.producto_param pp
    join gen.catalogo c using (sku)
    left join gen.escenario e using (sku)
    where pp.r_precio < 0.5 and e.sku is null;

  insert into inventario (producto_id, stock_actual, coste_medio_usd, actualizado_en)
    select producto_id, 0, 0, gen.ts(date '2025-09-01', 9) from gen.producto_param;

  -- Compra inicial por proveedor, recibida el 30/09/2025.
  for s in select distinct proveedor_id from gen.producto_param loop
    insert into compras (negocio_id, proveedor_id, fecha, estado, total_usd)
      values (neg, s.proveedor_id, gen.ts(date '2025-09-26', 15), 'pendiente', 0) returning id into cid;
    insert into lineas_compra (compra_id, producto_id, cantidad, coste_unitario_usd)
      select cid, pp.producto_id,
             greatest(ceil(pp.demanda * gen.estacional(pp.perfil, date '2025-10-01') * pp.cobertura),
                      case when pp.linea = 'Envíos' then 2 else 6 end),
             gen.coste(pp.producto_id, date '2025-09-26')
      from gen.producto_param pp left join gen.escenario e using (sku)
      where pp.proveedor_id = s.proveedor_id
        and pp.perfil not in ('madres', 'fin_ano')
        and not coalesce(e.sin_precio, false);
    update compras set total_usd = (select coalesce(sum(cantidad * coste_unitario_usd), 0) from lineas_compra where compra_id = cid)
      where id = cid;
    insert into gen.llegadas values (cid, date '2025-09-30', true);
  end loop;
  perform gen.recibir(date '2025-09-30');
end $$;

-- Recepción de compras ------------------------------------------------------

create function gen.recibir(d date) returns void language plpgsql as $$
declare c record; l record;
begin
  for c in
    select co.id, ll.especial from compras co join gen.llegadas ll on ll.compra_id = co.id
    where ll.fecha_llegada = d and co.estado = 'pendiente'
  loop
    if not c.especial and gen.rnd() < 0.01 then
      update compras set estado = 'cancelada' where id = c.id;   -- el proveedor no sirvió
      continue;
    end if;
    for l in select * from lineas_compra where compra_id = c.id loop
      update inventario
        set coste_medio_usd = round((stock_actual * coste_medio_usd + l.cantidad * l.coste_unitario_usd)
                                    / (stock_actual + l.cantidad), 4),
            stock_actual = stock_actual + l.cantidad,
            actualizado_en = gen.ts(d, 6.5)
        where producto_id = l.producto_id;
      insert into movimientos_inventario (producto_id, fecha, tipo, cantidad, referencia_tipo, referencia_id)
        values (l.producto_id, gen.ts(d, 6.5), 'compra', l.cantidad, 'compra', c.id);
    end loop;
    update compras set estado = 'recibida' where id = c.id;
  end loop;
end $$;

-- Reposición automática y compras especiales ------------------------------

create function gen.reponer(d date) returns void language plpgsql as $$
declare neg bigint := (select id from negocios limit 1); s record; cid bigint;
begin
  for s in
    select ce.*, pp.producto_id, pp.proveedor_id
    from gen.compras_especiales ce join gen.producto_param pp using (sku)
    where ce.fecha = d
  loop
    insert into compras (negocio_id, proveedor_id, fecha, estado, total_usd)
      values (neg, s.proveedor_id, gen.ts(d, 15), 'pendiente', 0) returning id into cid;
    insert into lineas_compra (compra_id, producto_id, cantidad, coste_unitario_usd)
      values (cid, s.producto_id, s.cantidad, gen.coste(s.producto_id, d));
    update compras set total_usd = (select sum(cantidad * coste_unitario_usd) from lineas_compra where compra_id = cid)
      where id = cid;
    insert into gen.llegadas values (cid, d + s.plazo, true);
  end loop;

  truncate gen.tmp_pedido;
  insert into gen.tmp_pedido
    select pp.producto_id, pp.proveedor_id,
           greatest(ceil(pp.demanda * gen.estacional(pp.perfil, d) * pp.cobertura),
                    case when pp.linea = 'Envíos' then 2 else 6 end),
           pp.plazo_min + floor(gen.rnd() * (pp.plazo_max - pp.plazo_min + 1))::int
    from gen.producto_param pp
    join inventario i using (producto_id)
    left join gen.escenario e using (sku)
    where pp.perfil not in ('madres', 'fin_ano') and pp.demanda > 0
      and (e.sin_reposicion_desde is null or d < e.sin_reposicion_desde)
      and (e.demanda_cero_desde is null or d < e.demanda_cero_desde - 30)
      and (e.descatalogado_desde is null or d < e.descatalogado_desde - 31)
      and not coalesce(e.sin_precio, false)
      and i.stock_actual + coalesce((
            select sum(lc.cantidad) from lineas_compra lc join compras co on co.id = lc.compra_id
            where co.estado = 'pendiente' and lc.producto_id = pp.producto_id), 0)
          <= ceil(pp.demanda * gen.estacional(pp.perfil, d) * (pp.plazo_max + 3));

  for s in select proveedor_id, min(plazo) as plazo from gen.tmp_pedido group by proveedor_id loop
    insert into compras (negocio_id, proveedor_id, fecha, estado, total_usd)
      values (neg, s.proveedor_id, gen.ts(d, 16), 'pendiente', 0) returning id into cid;
    insert into lineas_compra (compra_id, producto_id, cantidad, coste_unitario_usd)
      select cid, producto_id, cantidad, gen.coste(producto_id, d)
      from gen.tmp_pedido where proveedor_id = s.proveedor_id;
    update compras set total_usd = (select sum(cantidad * coste_unitario_usd) from lineas_compra where compra_id = cid)
      where id = cid;
    insert into gen.llegadas values (cid, d + s.plazo, false);
  end loop;
end $$;

-- Devoluciones programadas ----------------------------------------------------

create function gen.procesar_devoluciones(d date, hora_corte numeric default 24) returns void language plpgsql as $$
declare r record;
begin
  for r in
    select dp.* from gen.devoluciones_pendientes dp join ventas v on v.id = dp.venta_id
    where (dp.fecha at time zone 'America/Havana')::date = d and v.estado = 'completada'
      and dp.fecha <= gen.ts(d, hora_corte)
  loop
    insert into devoluciones (linea_venta_id, fecha, cantidad, motivo, reembolso_usd, reingresa_stock)
      values (r.linea_venta_id, r.fecha, r.cantidad, r.motivo, r.reembolso, r.reingresa);
    if r.reingresa then
      update inventario set stock_actual = stock_actual + r.cantidad, actualizado_en = r.fecha
        where producto_id = r.producto_id;
      insert into movimientos_inventario (producto_id, fecha, tipo, cantidad, referencia_tipo, referencia_id)
        values (r.producto_id, r.fecha, 'devolucion', r.cantidad, 'devolucion', r.linea_venta_id);
    end if;
  end loop;
  delete from gen.devoluciones_pendientes where fecha <= gen.ts(d, hora_corte);
end $$;

-- Cierre de una venta: totales, pagos, anulación y devolución futura --------

create function gen.cerrar_venta(vid bigint, d date) returns void language plpgsql as $$
declare
  v ventas; tu numeric; tc numeric; r float; usd_parte numeric; resto numeric; l record;
  pd numeric; p_anular numeric; defecto boolean; motivo text;
begin
  select sum(cantidad * precio_unitario_usd), sum(cantidad * precio_unitario_cup) into tu, tc
    from lineas_venta where venta_id = vid;
  if tu is null then
    delete from ventas where id = vid;
    return;
  end if;
  update ventas set total_usd = tu, total_cup = tc where id = vid returning * into v;

  p_anular := case when d between '2026-09-21' and '2026-09-27' then 0.06 else 0.012 end;  -- semana sembrada
  if gen.rnd() < p_anular then
    update ventas
      set estado = 'anulada',
          anulada_en = v.fecha + (5 + gen.rnd() * 85) * interval '1 minute',
          motivo_anulacion = (array['Error en el cobro', 'Cliente desistió de la compra',
                                    'Producto duplicado en la factura', 'Transferencia no confirmada'])[1 + floor(gen.rnd() * 4)::int]
      where id = vid returning * into v;
    for l in select * from lineas_venta where venta_id = vid loop
      update inventario set stock_actual = stock_actual + l.cantidad, actualizado_en = v.anulada_en
        where producto_id = l.producto_id;
      insert into movimientos_inventario (producto_id, fecha, tipo, cantidad, referencia_tipo, referencia_id)
        values (l.producto_id, v.anulada_en, 'anulacion_venta', l.cantidad, 'venta', vid);
    end loop;
    return;
  end if;

  r := gen.rnd();
  if v.canal = 'web' then
    if r < 0.65 then insert into pagos (venta_id, moneda, metodo, importe) values (vid, 'CUP', 'transferencia', tc);
    elsif r < 0.85 then insert into pagos (venta_id, moneda, metodo, importe) values (vid, 'USD', 'efectivo', tu);
    else insert into pagos (venta_id, moneda, metodo, importe) values (vid, 'CUP', 'efectivo', tc);
    end if;
  elsif (tu >= 300 and r < 0.6) or (tu < 300 and r >= 0.75 and r < 0.95) then
    insert into pagos (venta_id, moneda, metodo, importe) values (vid, 'USD', 'efectivo', tu);
  elsif (tu >= 300 and r < 0.9) or (tu < 300 and r >= 0.45 and r < 0.75) then
    insert into pagos (venta_id, moneda, metodo, importe) values (vid, 'CUP', 'transferencia', tc);
  elsif tu < 300 and r < 0.45 then
    insert into pagos (venta_id, moneda, metodo, importe) values (vid, 'CUP', 'efectivo', tc);
  else
    -- Pago mixto: una parte en USD efectivo y el resto por transferencia en CUP.
    usd_parte := floor(tu / 2);
    if usd_parte < 1 then
      insert into pagos (venta_id, moneda, metodo, importe) values (vid, 'CUP', 'efectivo', tc);
    else
      resto := ceil((tc - usd_parte * v.tasa_usd_cup) / 10) * 10;
      insert into pagos (venta_id, moneda, metodo, importe) values (vid, 'USD', 'efectivo', usd_parte);
      if resto > 0 then
        insert into pagos (venta_id, moneda, metodo, importe) values (vid, 'CUP', 'transferencia', resto);
      end if;
    end if;
  end if;

  for l in select lv.*, pp.sku from lineas_venta lv join gen.producto_param pp using (producto_id) where lv.venta_id = vid loop
    pd := coalesce((select e.devolucion_prob from gen.escenario e
                    where e.sku = l.sku and e.devolucion_desde is not null and d >= e.devolucion_desde), 0.005);
    if gen.rnd() < pd then
      defecto := pd > 0.005 or gen.rnd() < 0.4;
      motivo := case when defecto then 'Producto defectuoso'
                     when gen.rnd() < 0.5 then 'No era lo que esperaba' else 'Error en el pedido' end;
      insert into gen.devoluciones_pendientes values (
        l.id, vid, l.producto_id, gen.ts(d + 1 + floor(gen.rnd() * 7)::int, 10 + gen.rnd() * 7),
        1, motivo, l.precio_unitario_usd, not defecto);
    end if;
  end loop;
end $$;

-- Simulación de un día ------------------------------------------------------

create function gen.simular_dia(d date, hora_corte numeric default 24) returns void language plpgsql as $$
declare
  neg bigint := (select id from negocios limit 1);
  tasa numeric;
  dow int := extract(isodow from d);
  abre numeric := 9;
  cierra numeric := case when extract(isodow from d) = 7 then 13 else 19 end;
  f_glob numeric; f_fis numeric; f_web numeric;
  p record; ln record; lam numeric; n int; q int;
  vid bigint; vfecha timestamptz; canal_actual text; restantes int := 0; hora numeric;
  stock numeric; coste numeric;
begin
  select usd_cup into tasa from tasas_cambio where fecha = d;
  perform gen.recibir(d);

  -- Factores de demanda del día (mercado cubano).
  f_glob := 0.75 + 0.2 * (d - date '2025-10-01') / 365.0;                       -- crecimiento del negocio
  if extract(day from d) <= 5 then f_glob := f_glob * 1.15; end if;            -- remesas y cobros
  if extract(month from d) = 12 then
    f_glob := f_glob * case when extract(day from d) >= 24 then 1.5 else 1.2 end;
  end if;
  if d between '2026-05-04' and '2026-05-10' then f_glob := f_glob * 1.3; end if;  -- Día de las Madres
  if d = '2026-09-29' then f_glob := f_glob * 0.5; end if;                     -- anomalía sembrada: ayer
  f_fis := f_glob * case dow when 1 then 0.9 when 2 then 0.9 when 3 then 0.95 when 4 then 1
                             when 5 then 1.15 when 6 then 1.3 else 0.7 end;
  f_web := f_glob * case dow when 6 then 1.1 else 1 end;
  if d in ('2025-10-10', '2025-12-25', '2026-01-01', '2026-05-01', '2026-07-25', '2026-07-26', '2026-07-27') then
    f_fis := 0;                                                                 -- festivo: tienda cerrada
    f_web := f_web * 0.6;
  end if;
  if abs(hashtext('apagon' || d::text)) % 100 < 10 then f_fis := f_fis * 0.55; end if;  -- apagón
  if d between '2026-08-10' and '2026-08-16' then                              -- semana de apagones largos
    f_fis := f_fis * 0.5;
    f_web := f_web * 0.8;
  end if;
  if hora_corte < 24 then                                                      -- día en curso
    f_fis := f_fis * greatest(0, least(hora_corte, cierra) - abre) / (cierra - abre);
    f_web := f_web * greatest(0, hora_corte - 7) / 16.0;
  end if;

  -- Líneas de venta del día por producto y canal.
  truncate gen.tmp_lineas;
  for p in
    select pp.*, pr.precio_usd, e.demanda_cero_desde, e.descatalogado_desde
    from gen.producto_param pp
    join precios_producto pr on pr.producto_id = pp.producto_id
      and pr.vigente_desde <= gen.ts(d, 0) and (pr.vigente_hasta is null or pr.vigente_hasta > gen.ts(d, 0))
    left join gen.escenario e using (sku)
  loop
    continue when p.demanda_cero_desde is not null and d >= p.demanda_cero_desde;
    lam := p.demanda * gen.estacional(p.perfil, d);
    n := gen.poisson(lam * (1 - p.cuota_web) * f_fis);
    while n > 0 loop
      q := case when p.linea = 'Mercado' and p.categoria <> 'Combos' then least(n, 1 + floor(gen.rnd() * 4)::int) else 1 end;
      insert into gen.tmp_lineas values ('tienda_fisica', p.producto_id, q, p.precio_usd, gen.rnd());
      n := n - q;
    end loop;
    n := gen.poisson(lam * p.cuota_web * f_web);
    while n > 0 loop
      q := case when p.linea = 'Mercado' and p.categoria <> 'Combos' then least(n, 1 + floor(gen.rnd() * 4)::int) else 1 end;
      insert into gen.tmp_lineas values ('web', p.producto_id, q, p.precio_usd, gen.rnd());
      n := n - q;
    end loop;
  end loop;

  -- Agrupación en tickets.
  for ln in select * from gen.tmp_lineas order by canal, orden loop
    if vid is null or restantes = 0 or ln.canal <> canal_actual then
      if vid is not null then perform gen.cerrar_venta(vid, d); end if;
      canal_actual := ln.canal;
      restantes := case when ln.canal = 'web' then 2 + floor(gen.rnd() * 4)::int else 1 + floor(gen.rnd() * 4)::int end;
      hora := case when ln.canal = 'web' then 7 + gen.rnd() * greatest(least(16, hora_corte - 7), 0.01)
                   else abre + gen.rnd() * (least(cierra, hora_corte) - abre) end;
      vfecha := gen.ts(d, hora);
      insert into ventas (negocio_id, numero, canal, fecha, estado, tasa_usd_cup, total_usd, total_cup)
        values (neg, 'TMP-' || gen_random_uuid(), ln.canal, vfecha, 'completada', tasa, 0, 0)
        returning id into vid;
    end if;
    restantes := restantes - 1;
    select stock_actual, coste_medio_usd into stock, coste from inventario where producto_id = ln.producto_id;
    q := least(ln.cantidad, floor(stock)::int);
    continue when q <= 0;                                                       -- sin stock: venta perdida
    insert into lineas_venta (venta_id, producto_id, cantidad, precio_unitario_usd, precio_unitario_cup, coste_unitario_usd)
      values (vid, ln.producto_id, q, ln.precio_usd, ceil(ln.precio_usd * tasa / 10) * 10, coste);
    update inventario set stock_actual = stock_actual - q, actualizado_en = vfecha where producto_id = ln.producto_id;
    insert into movimientos_inventario (producto_id, fecha, tipo, cantidad, referencia_tipo, referencia_id)
      values (ln.producto_id, vfecha, 'venta', -q, 'venta', vid);
  end loop;
  if vid is not null then perform gen.cerrar_venta(vid, d); end if;
  -- Devoluciones después de las ventas: sus unidades no se usan en ventas anteriores del mismo día.
  perform gen.procesar_devoluciones(d, hora_corte);

  -- Numeración correlativa por canal y día, en orden cronológico.
  update ventas v
    set numero = case x.canal when 'web' then 'WEB-' else 'TF-' end || to_char(d, 'YYYYMMDD') || '-' || lpad(x.rn::text, 4, '0')
    from (select id, canal, row_number() over (partition by canal order by fecha) as rn
          from ventas where numero like 'TMP-%') x
    where v.id = x.id;

  if hora_corte >= 24 then
    -- Mermas de alimentos.
    for p in
      select pp.producto_id from gen.producto_param pp join inventario i using (producto_id)
      where pp.categoria = 'Alimentos' and i.stock_actual >= 1 and gen.rnd() < 0.004
    loop
      update inventario set stock_actual = stock_actual - 1, actualizado_en = gen.ts(d, 18.5) where producto_id = p.producto_id;
      insert into movimientos_inventario (producto_id, fecha, tipo, cantidad, referencia_tipo)
        values (p.producto_id, gen.ts(d, 18.5), 'merma', -1, 'ajuste');
    end loop;
    -- Conteo de fin de mes: pequeños ajustes.
    if d = (date_trunc('month', d) + interval '1 month - 1 day')::date then
      for p in select producto_id from inventario where stock_actual >= 3 order by gen.rnd() limit 4 loop
        q := case when gen.rnd() < 0.5 then 1 else -1 end;
        update inventario set stock_actual = stock_actual + q, actualizado_en = gen.ts(d, 19) where producto_id = p.producto_id;
        insert into movimientos_inventario (producto_id, fecha, tipo, cantidad, referencia_tipo)
          values (p.producto_id, gen.ts(d, 19), case when q > 0 then 'ajuste_positivo' else 'ajuste_negativo' end, q, 'ajuste');
      end loop;
    end if;
    perform gen.reponer(d);
  end if;
end $$;

create function gen.simular_rango(desde date, hasta date, hora_corte_ultimo numeric default 24) returns void
language plpgsql as $$
declare d date := desde;
begin
  perform setseed(((desde - date '2025-01-01') % 1000) / 1000.0);
  while d <= hasta loop
    perform gen.simular_dia(d, case when d = hasta then hora_corte_ultimo else 24 end);
    d := d + 1;
  end loop;
end $$;

create function gen.finalizar() returns void language plpgsql as $$
begin
  -- Devoluciones sembradas de forma determinista (~22 % de las líneas del producto con defecto).
  -- No reingresan al stock, así que no alteran el inventario.
  insert into devoluciones (linea_venta_id, fecha, cantidad, motivo, reembolso_usd, reingresa_stock)
    select lv.id,
           least(v.fecha + (1 + abs(hashtext('dev' || lv.id::text)) % 3) * interval '1 day', gen.ts(date '2026-09-30', 10)),
           1, 'Producto defectuoso', lv.precio_unitario_usd, false
    from lineas_venta lv
    join ventas v on v.id = lv.venta_id
    join productos p on p.id = lv.producto_id
    join gen.escenario e on e.sku = p.sku
    where e.devolucion_prob is not null and v.estado = 'completada'
      and (v.fecha at time zone 'America/Havana')::date >= e.devolucion_desde
      and v.fecha < gen.ts(date '2026-09-29', 0)
      and not exists (select 1 from devoluciones d where d.linea_venta_id = lv.id)
      and abs(hashtext('dev' || lv.id::text)) % 100 < 22;
  update productos p set activo = false
    from gen.escenario e where e.sku = p.sku and e.descatalogado_desde is not null;
end $$;
