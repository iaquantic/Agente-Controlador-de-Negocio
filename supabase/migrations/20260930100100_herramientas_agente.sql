-- Alertas y las 12 herramientas públicas del esquema `agente`.

-- Reglas de alerta (05 §5.6). Una fila por alerta activa.
create function agente._alertas()
returns table (alert_key text, regla text, prioridad text, orden int, categoria text, sku text, nombre text,
               titulo text, detalle text, valor_actual numeric, umbral numeric, prioritario boolean)
language plpgsql stable as $$
declare
  hoy date := agente._hoy();
  ahora timestamptz := agente._ahora();
  r record;
  t_hoy numeric; t_7 numeric;
  n_tickets bigint; n_anul bigint;
  ultima timestamptz;
begin
  -- Producto a producto.
  for r in select * from agente._productos() loop
    if r.estado = 'agotado' then
      regla := case when r.prioritario then 'agotado_prioritario' else 'agotado' end;
      prioridad := case when r.prioritario then 'urgent' else 'high' end;
      titulo := r.nombre || ' agotado';
      detalle := format('Sin stock desde hace %s días; vendía %s u/día.%s', coalesce(r.dias_sin_stock, 0),
                        round(r.uds_60d / agente._p('agotado_demanda_dias'), 1),
                        case when r.pendiente > 0 then format(' Hay %s u en camino.', round(r.pendiente)) else ' No hay compras en camino.' end);
      valor_actual := 0; umbral := 0;
    elsif r.estado = 'riesgo_rotura' then
      regla := case when r.prioritario then 'riesgo_rotura_prioritario' else 'riesgo_rotura' end;
      prioridad := case when r.prioritario then 'urgent' else 'high' end;
      titulo := r.nombre || ': riesgo de quedarse sin stock';
      detalle := format('Quedan %s u (unos %s días) y reponer tarda %s días.%s', round(r.stock), round(r.cobertura),
                        r.plazo_dias,
                        case when r.pendiente > 0 then format(' Hay %s u en camino.', round(r.pendiente)) else ' No hay compras en camino.' end);
      valor_actual := r.cobertura; umbral := r.plazo_dias;
    elsif r.estado = 'stock_bajo' then
      regla := 'stock_bajo'; prioridad := 'medium';
      titulo := r.nombre || ': stock bajo';
      detalle := format('Quedan %s u; el mínimo es %s u.', round(r.stock), round(r.stock_minimo));
      valor_actual := r.stock; umbral := r.stock_minimo;
    elsif r.estado = 'exceso' then
      regla := 'exceso_stock'; prioridad := 'medium';
      titulo := r.nombre || ': exceso de stock';
      detalle := format('Hay %s u, suficiente para unos %s días (%s USD a coste).', round(r.stock), round(r.cobertura), r.valor_stock);
      valor_actual := r.cobertura; umbral := agente._p('exceso_dias');
    elsif r.estado = 'sin_movimiento' then
      regla := 'sin_movimiento'; prioridad := 'medium';
      titulo := r.nombre || ': sin ventas en 30 días';
      detalle := format('Tiene %s u en stock (%s USD a coste) y no se ha vendido en 30 días.', round(r.stock), r.valor_stock);
      valor_actual := 0; umbral := agente._p('sin_movimiento_dias');
    elsif r.estado = 'agotado_sin_demanda' and r.activo then
      regla := 'agotado_sin_demanda'; prioridad := 'low';
      titulo := r.nombre || ' agotado (sin demanda reciente)';
      detalle := format('Sin stock y sin ventas en %s días.', agente._p('agotado_demanda_dias'));
      valor_actual := 0; umbral := 0;
    elsif r.estado = 'inactivo' and r.stock > 0 then
      regla := 'inactivo_con_stock'; prioridad := 'low';
      titulo := r.nombre || ': desactivado con stock';
      detalle := format('Está desactivado pero quedan %s u (%s USD a coste).', round(r.stock), r.valor_stock);
      valor_actual := r.stock; umbral := 0;
    else
      regla := null;
    end if;
    if regla is not null then
      alert_key := regla || ':' || r.sku || ':' || hoy; orden := 0; categoria := 'inventario';
      sku := r.sku; nombre := r.nombre; prioritario := r.prioritario;
      return next;
    end if;

    if r.activo and r.estado in ('normal', 'stock_bajo', 'exceso') and r.baja_rotacion and r.estado <> 'exceso' then
      alert_key := 'baja_rotacion:' || r.sku || ':' || hoy; regla := 'baja_rotacion'; prioridad := 'low'; orden := 0;
      categoria := 'inventario'; sku := r.sku; nombre := r.nombre; prioritario := r.prioritario;
      titulo := r.nombre || ': se vende poco';
      detalle := format('Vende %s u/día, menos del %s %% de lo normal en su categoría.', r.velocidad, agente._p('baja_rotacion_pct'));
      valor_actual := r.velocidad; umbral := null;
      return next;
    end if;

    if r.activo and r.devueltas_30d >= agente._p('devoluciones_min_uds') and r.uds_30d > 0
       and r.devueltas_30d / r.uds_30d * 100 > agente._p('devoluciones_pct') then
      alert_key := 'devoluciones_anomalas:' || r.sku || ':' || hoy; regla := 'devoluciones_anomalas'; prioridad := 'high';
      orden := 0; categoria := 'devoluciones'; sku := r.sku; nombre := r.nombre; prioritario := r.prioritario;
      titulo := r.nombre || ': muchas devoluciones';
      detalle := format('Devueltas %s de %s u vendidas en 30 días (%s %%).', round(r.devueltas_30d), round(r.uds_30d),
                        round(r.devueltas_30d / r.uds_30d * 100, 1));
      valor_actual := round(r.devueltas_30d / r.uds_30d * 100, 1); umbral := agente._p('devoluciones_pct');
      return next;
    end if;

    if r.activo and r.uds_30d >= agente._p('margen_min_unidades') and r.margen_30d < agente._p('margen_minimo_pct') then
      regla := case when r.prioritario then 'margen_bajo_prioritario' else 'margen_bajo' end;
      prioridad := case when r.prioritario then 'high' else 'medium' end;
      alert_key := regla || ':' || r.sku || ':' || hoy; orden := 0; categoria := 'rentabilidad';
      sku := r.sku; nombre := r.nombre; prioritario := r.prioritario;
      titulo := r.nombre || ': margen bajo';
      detalle := format('Margen bruto de %s %% en los últimos 30 días.', r.margen_30d);
      valor_actual := r.margen_30d; umbral := agente._p('margen_minimo_pct');
      return next;
    end if;

    if r.activo and r.precio_usd is null then
      alert_key := 'producto_sin_precio:' || r.sku || ':' || hoy; regla := 'producto_sin_precio'; prioridad := 'high';
      orden := 0; categoria := 'calidad_datos'; sku := r.sku; nombre := r.nombre; prioritario := r.prioritario;
      titulo := r.nombre || ' no tiene precio';
      detalle := format('Está activo con %s u en stock pero sin precio vigente: no se puede vender.', round(r.stock));
      valor_actual := null; umbral := null;
      return next;
    end if;
  end loop;

  -- Globales.
  sku := null; nombre := null; prioritario := false; orden := 0;

  -- Caída o pico de ventas del día (desde la hora mínima).
  if extract(hour from ahora at time zone 'America/Havana') >= agente._p('hora_min_caida') then
    for r in select * from agente._dia_vs_esperado(hoy) loop
      if r.net_esperado >= agente._p('esperado_min_usd') and r.variacion_pct <= agente._p('caida_ventas_pct') then
        alert_key := 'caida_ventas_dia:global:' || hoy; regla := 'caida_ventas_dia'; prioridad := 'urgent'; categoria := 'ventas';
        titulo := 'Las ventas de hoy van muy por debajo de lo normal';
        detalle := format('%s USD hasta las %s frente a %s USD esperados (%s %%).', r.net_hoy, agente._horas(r.hasta),
                          r.net_esperado, r.variacion_pct);
        valor_actual := r.variacion_pct; umbral := agente._p('caida_ventas_pct');
        return next;
      elsif r.net_esperado >= agente._p('esperado_min_usd') and r.variacion_pct >= agente._p('pico_ventas_pct') then
        alert_key := 'pico_ventas_dia:global:' || hoy; regla := 'pico_ventas_dia'; prioridad := 'medium'; categoria := 'ventas';
        titulo := 'Las ventas de hoy van muy por encima de lo normal';
        detalle := format('%s USD hasta las %s frente a %s USD esperados (+%s %%).', r.net_hoy, agente._horas(r.hasta),
                          r.net_esperado, r.variacion_pct);
        valor_actual := r.variacion_pct; umbral := agente._p('pico_ventas_pct');
        return next;
      end if;
    end loop;
  end if;

  -- Datos desactualizados.
  select max(fecha) into ultima from public.ventas where negocio_id = agente._neg() and fecha <= ahora;
  if (agente._abierto(ahora) and (ultima is null or ahora - ultima > agente._p('frescura_max_min') * interval '1 minute'))
     or not exists (select 1 from public.tasas_cambio where fecha = hoy) then
    alert_key := 'datos_desactualizados:global:' || hoy; regla := 'datos_desactualizados'; prioridad := 'high';
    categoria := 'calidad_datos';
    titulo := 'Los datos pueden estar desactualizados';
    detalle := format('Última venta registrada a las %s%s.', coalesce(agente._horas(ultima), '—'),
                      case when not exists (select 1 from public.tasas_cambio where fecha = hoy) then '; falta la tasa de hoy' else '' end);
    valor_actual := null; umbral := agente._p('frescura_max_min');
    return next;
  end if;

  -- Anulaciones de los últimos 7 días.
  select count(*), count(*) filter (where estado = 'anulada') into n_tickets, n_anul
  from public.ventas where negocio_id = agente._neg() and fecha > ahora - interval '7 days' and fecha <= ahora;
  if n_tickets >= agente._p('anulaciones_min_tickets') and n_anul::numeric / n_tickets * 100 > agente._p('anulaciones_pct') then
    alert_key := 'anulaciones_altas:global:' || hoy; regla := 'anulaciones_altas'; prioridad := 'high'; categoria := 'anulaciones';
    titulo := 'Muchas ventas anuladas esta semana';
    detalle := format('%s de %s ventas anuladas en los últimos 7 días (%s %%).', n_anul, n_tickets,
                      round(n_anul::numeric / n_tickets * 100, 1));
    valor_actual := round(n_anul::numeric / n_tickets * 100, 1); umbral := agente._p('anulaciones_pct');
    return next;
  end if;

  -- Variación de la tasa en 7 días.
  t_hoy := agente._tasa(hoy); t_7 := agente._tasa(hoy - 7);
  if t_7 > 0 and abs(agente._pct(t_hoy, t_7)) >= agente._p('tasa_variacion_pct') then
    alert_key := 'tasa_variacion:global:' || hoy; regla := 'tasa_variacion'; prioridad := 'high'; categoria := 'tasa';
    titulo := case when t_hoy > t_7 then 'El dólar ha subido fuerte esta semana' else 'El dólar ha bajado fuerte esta semana' end;
    detalle := format('La tasa pasó de %s a %s CUP/USD en 7 días (%s %%).', t_7, t_hoy, agente._pct(t_hoy, t_7));
    valor_actual := agente._pct(t_hoy, t_7); umbral := agente._p('tasa_variacion_pct');
    return next;
  end if;

  -- Margen bajo por categoría.
  for r in
    select pc.nombre cat,
           sum(lv.cantidad * lv.precio_unitario_usd) ing, sum(lv.cantidad * lv.coste_unitario_usd) cos
    from public.lineas_venta lv join public.ventas v on v.id = lv.venta_id
    join public.productos p on p.id = lv.producto_id join public.categorias sc on sc.id = p.categoria_id
    join public.categorias pc on pc.id = sc.categoria_padre_id
    where v.estado = 'completada' and v.negocio_id = agente._neg() and v.fecha > ahora - interval '30 days' and v.fecha <= ahora
    group by 1 having sum(lv.cantidad * lv.precio_unitario_usd) > 0
  loop
    if (r.ing - r.cos) / r.ing * 100 < agente._p('margen_minimo_pct') then
      alert_key := 'margen_bajo:' || r.cat || ':' || hoy; regla := 'margen_bajo'; prioridad := 'medium'; categoria := 'rentabilidad';
      titulo := 'Margen bajo en ' || r.cat;
      detalle := format('Margen bruto de %s %% en los últimos 30 días.', round((r.ing - r.cos) / r.ing * 100, 1));
      valor_actual := round((r.ing - r.cos) / r.ing * 100, 1); umbral := agente._p('margen_minimo_pct');
      return next;
    end if;
  end loop;

  -- Compras retrasadas.
  for r in
    select c.id, pr.nombre prov, (hoy - (c.fecha at time zone 'America/Havana')::date) dias,
           max(cc.plazo_dias) plazo
    from public.compras c join public.proveedores pr on pr.id = c.proveedor_id
    join public.lineas_compra lc on lc.compra_id = c.id join public.productos p on p.id = lc.producto_id
    join public.categorias sc on sc.id = p.categoria_id join public.categorias pc on pc.id = sc.categoria_padre_id
    join agente.config_categoria cc on cc.nombre = pc.nombre
    where c.estado = 'pendiente' and c.negocio_id = agente._neg()
    group by c.id, pr.nombre, c.fecha
    having (hoy - (c.fecha at time zone 'America/Havana')::date) > max(cc.plazo_dias) + agente._p('compra_retraso_extra_dias')
  loop
    alert_key := 'compra_retrasada:' || r.id || ':' || hoy; regla := 'compra_retrasada'; prioridad := 'low'; categoria := 'inventario';
    titulo := 'Compra retrasada de ' || r.prov;
    detalle := format('Pedida hace %s días; el plazo normal es de %s días.', r.dias, r.plazo);
    valor_actual := r.dias; umbral := r.plazo;
    return next;
  end loop;
end $$;

create function agente._alertas_json(p_prio text, p_cat text) returns jsonb language sql stable as $$
  with a as (
    select *, case prioridad when 'urgent' then 1 when 'high' then 2 when 'medium' then 3 else 4 end nivel
    from agente._alertas()
  ), f as (
    select * from a
    where nivel <= case p_prio when 'urgent' then 1 when 'high' then 2 when 'medium' then 3 else 4 end
      and (p_cat is null or a.categoria = p_cat)
  )
  select jsonb_build_object(
    'alerts', coalesce((select jsonb_agg(jsonb_build_object(
        'alert_key', alert_key, 'rule', regla, 'priority', prioridad, 'category', f.categoria,
        'product', case when sku is null then null else jsonb_build_object('sku', sku, 'name', nombre) end,
        'priority_product', prioritario,
        'title', titulo, 'detail', detalle, 'current_value', valor_actual, 'threshold', umbral,
        'detected_at', agente._iso(agente._ahora()))
        order by nivel, prioritario desc, titulo) from f), '[]'::jsonb),
    'count_by_priority', jsonb_build_object(
        'urgent', (select count(*) from a where nivel = 1), 'high', (select count(*) from a where nivel = 2),
        'medium', (select count(*) from a where nivel = 3), 'low', (select count(*) from a where nivel = 4)))
$$;

-- 1. get_business_summary -----------------------------------------------------
create function agente.get_business_summary(p jsonb default '{}') returns jsonb
language plpgsql stable security definer set search_path = agente, public, extensions, pg_temp as $$
declare
  d date; hasta timestamptz; r record; hoy_j jsonb; mes jsonb; mes_prev jsonb; t7 numeric;
begin
  perform agente._claves(p, array['date']);
  d := agente._fecha(p, 'date', agente._hoy());
  if d > agente._hoy() then perform agente._error('invalid_params', 'La fecha no puede ser futura.'); end if;
  select * into r from agente._dia_vs_esperado(d);
  hasta := r.hasta;
  hoy_j := agente._totales(agente._ts(d), hasta, 'all');
  mes := agente._totales(agente._ts(date_trunc('month', d)::date), hasta, 'all');
  mes_prev := agente._totales(agente._ts((date_trunc('month', d) - interval '1 month')::date),
                              agente._ts((date_trunc('month', d) - interval '1 month')::date) + (hasta - agente._ts(date_trunc('month', d)::date)),
                              'all');
  t7 := agente._tasa(d - 7);
  return agente._sobre('get_business_summary', jsonb_build_object('date', d), d, d, jsonb_build_object(
    'date', d,
    'as_of_hour', agente._horas(hasta),
    'is_partial_day', hasta < agente._ts(d + 1),
    'store_open_today', agente._abierto(agente._ts(d) + interval '10 hours'),
    'today', hoy_j || jsonb_build_object('by_channel', (
        select jsonb_agg(jsonb_build_object('channel', s.clave, 'net_usd', round(s.bruto_usd - s.devol_usd, 2), 'tickets', s.tickets)
                         order by s.clave)
        from agente._serie(agente._ts(d), hasta, 'all', 'channel') s)),
    'expected', jsonb_build_object('basis', 'media de los 4 mismos días de la semana anteriores hasta la misma hora',
                                   'net_usd', r.net_esperado, 'tickets', r.tickets_esperado),
    'vs_expected_pct', r.variacion_pct,
    'month_to_date', jsonb_build_object('net_usd', mes -> 'net_usd', 'net_cup', mes -> 'net_cup', 'tickets', mes -> 'tickets',
                                        'gross_margin_pct', mes -> 'gross_margin_pct',
                                        'vs_prev_month_same_days_pct', agente._pct((mes ->> 'net_usd')::numeric, (mes_prev ->> 'net_usd')::numeric)),
    'alerts_count', agente._alertas_json('low', null) -> 'count_by_priority',
    'fx_today', agente._tasa(d),
    'fx_change_7d_pct', agente._pct(agente._tasa(d), t7)),
    array['net_usd', 'net_cup', 'avg_ticket_usd', 'gross_margin_pct', 'expected', 'vs_expected_pct', 'vs_prev_month_same_days_pct', 'fx_change_7d_pct', 'cogs_usd', 'gross_profit_usd'],
    array['tickets', 'units', 'voided_tickets', 'fx_today', 'as_of_hour']);
exception when others then
  if sqlstate = '57014' then raise; end if;
  declare h text; begin get stacked diagnostics h = pg_exception_hint; return agente._fallo('get_business_summary', sqlstate, sqlerrm, h); end;
end $$;

-- 2. get_sales_summary ---------------------------------------------------------
create function agente.get_sales_summary(p jsonb default '{}') returns jsonb
language plpgsql stable security definer set search_path = agente, public, extensions, pg_temp as $$
declare
  desde date; hasta date; agrupar text; comparar text; v_canal text;
  ini timestamptz; fin timestamptz; c_ini timestamptz; c_fin timestamptz; c_desde date; c_hasta date;
  tot jsonb; grupos jsonb; comp jsonb := null; ctot jsonb;
begin
  perform agente._claves(p, array['from', 'to', 'group_by', 'compare', 'channel']);
  desde := agente._fecha(p, 'from', null); hasta := agente._fecha(p, 'to', null);
  perform agente._rango(desde, hasta);
  agrupar := agente._enum(p, 'group_by', array['none', 'day', 'week', 'month', 'channel', 'payment_method', 'category'], 'none');
  comparar := agente._enum(p, 'compare', array['none', 'previous_period', 'previous_year'], 'none');
  v_canal := agente._enum(p, 'channel', array['all', 'tienda_fisica', 'web'], 'all');
  ini := agente._ts(desde); fin := agente._fin(hasta);
  if fin <= ini then perform agente._error('invalid_params', 'El periodo empieza en el futuro.'); end if;

  tot := agente._totales(ini, fin, v_canal);

  if agrupar = 'payment_method' then
    with pg as (
      select pa.metodo, pa.moneda, sum(pa.importe) imp,
             sum(case when pa.moneda = 'USD' then pa.importe else pa.importe / v.tasa_usd_cup end) eq
      from public.pagos pa join public.ventas v on v.id = pa.venta_id
      where v.negocio_id = agente._neg() and v.estado = 'completada' and v.fecha >= ini and v.fecha < fin
        and (v_canal = 'all' or v.canal = v_canal)
      group by 1, 2
    )
    select jsonb_agg(jsonb_build_object('method', metodo, 'currency', moneda,
                                        'amount', case when moneda = 'CUP' then round(imp, 0) else round(imp, 2) end,
                                        'amount_usd_equiv', round(eq, 2),
                                        'share_pct', round(eq / nullif(sum(eq) over (), 0) * 100, 1))
                     order by eq desc)
    into grupos from pg;
  elsif agrupar <> 'none' then
    select jsonb_agg(jsonb_build_object('key', s.clave)
                     || agente._totales_json(s.bruto_usd, s.bruto_cup, s.devol_usd, s.devol_cup, s.coste, s.tickets, s.unidades, s.anuladas)
                     order by s.clave)
    into grupos from agente._serie(ini, fin, v_canal, agrupar) s;
  end if;

  if comparar <> 'none' then
    if comparar = 'previous_period' then
      c_ini := ini - (agente._ts(hasta + 1) - ini); c_fin := c_ini + (fin - ini);
      c_desde := desde - (hasta - desde + 1); c_hasta := desde - 1;
    else
      c_ini := agente._ts((desde - interval '1 year')::date); c_fin := c_ini + (fin - ini);
      c_desde := (desde - interval '1 year')::date; c_hasta := (hasta - interval '1 year')::date;
    end if;
    ctot := agente._totales(c_ini, c_fin, v_canal);
    comp := jsonb_build_object(
      'period', jsonb_build_object('from', c_desde, 'to', c_hasta),
      'same_hours_as_current', fin < agente._ts(hasta + 1),
      'totals', ctot,
      'delta_pct', jsonb_build_object(
        'net_usd', agente._pct((tot ->> 'net_usd')::numeric, (ctot ->> 'net_usd')::numeric),
        'tickets', agente._pct((tot ->> 'tickets')::numeric, (ctot ->> 'tickets')::numeric),
        'avg_ticket_usd', agente._pct((tot ->> 'avg_ticket_usd')::numeric, (ctot ->> 'avg_ticket_usd')::numeric),
        'gross_profit_usd', agente._pct((tot ->> 'gross_profit_usd')::numeric, (ctot ->> 'gross_profit_usd')::numeric)),
      'data_available', (ctot ->> 'tickets')::int > 0);
  end if;

  return agente._sobre('get_sales_summary',
    jsonb_build_object('from', desde, 'to', hasta, 'group_by', agrupar, 'compare', comparar, 'channel', v_canal),
    desde, hasta,
    jsonb_build_object('totals', tot, 'groups', coalesce(grupos, '[]'::jsonb), 'comparison', comp,
                       'is_partial', fin < agente._ts(hasta + 1), 'data_until', agente._iso(fin)),
    array['gross_usd', 'returns_usd', 'net_usd', 'net_cup', 'avg_ticket_usd', 'cogs_usd', 'gross_profit_usd', 'gross_margin_pct', 'amount_usd_equiv', 'share_pct', 'delta_pct'],
    array['tickets', 'units', 'voided_tickets', 'amount']);
exception when others then
  if sqlstate = '57014' then raise; end if;
  declare h text; begin get stacked diagnostics h = pg_exception_hint; return agente._fallo('get_sales_summary', sqlstate, sqlerrm, h); end;
end $$;

-- 3. get_top_products ----------------------------------------------------------
create function agente.get_top_products(p jsonb default '{}') returns jsonb
language plpgsql stable security definer set search_path = agente, public, extensions, pg_temp as $$
declare
  desde date; hasta date; metrica text; orden text; lim int; v_cat text; con_cero boolean;
  ini timestamptz; fin timestamptz; res jsonb; n int;
begin
  perform agente._claves(p, array['from', 'to', 'metric', 'order', 'limit', 'category', 'include_zero_sales']);
  desde := agente._fecha(p, 'from', null); hasta := agente._fecha(p, 'to', null);
  perform agente._rango(desde, hasta);
  metrica := agente._enum(p, 'metric', array['units', 'revenue', 'gross_profit'], 'units');
  orden := agente._enum(p, 'order', array['top', 'bottom'], 'top');
  lim := agente._int(p, 'limit', 10, 1, agente._p('max_limit')::int);
  v_cat := agente._texto(p, 'category', false, 2, 60);
  con_cero := agente._bool(p, 'include_zero_sales', false);
  ini := agente._ts(desde); fin := agente._fin(hasta);

  with prod as (
    select p.id, p.sku, p.nombre, pc.nombre cat, sc.nombre subcat, p.activo
    from public.productos p join public.categorias sc on sc.id = p.categoria_id
    join public.categorias pc on pc.id = sc.categoria_padre_id
    where p.negocio_id = agente._neg()
      and (v_cat is null or agente._norm(pc.nombre) = agente._norm(v_cat) or agente._norm(sc.nombre) = agente._norm(v_cat))
  ), v as (
    select lv.producto_id, sum(lv.cantidad) u, sum(lv.cantidad * lv.precio_unitario_usd) r, sum(lv.cantidad * lv.coste_unitario_usd) c
    from public.lineas_venta lv join public.ventas v on v.id = lv.venta_id
    where v.estado = 'completada' and v.negocio_id = agente._neg() and v.fecha >= ini and v.fecha < fin
    group by 1
  ), d as (
    select lv.producto_id, sum(d.reembolso_usd) r,
           sum(case when d.reingresa_stock then d.cantidad * lv.coste_unitario_usd else 0 end) c
    from public.devoluciones d join public.lineas_venta lv on lv.id = d.linea_venta_id
    where d.fecha >= ini and d.fecha < fin group by 1
  ), m as (
    select prod.*, coalesce(v.u, 0) u, coalesce(v.r, 0) - coalesce(d.r, 0) rev,
           coalesce(v.r, 0) - coalesce(d.r, 0) - (coalesce(v.c, 0) - coalesce(d.c, 0)) gp
    from prod left join v on v.producto_id = prod.id left join d on d.producto_id = prod.id
    where v.u is not null or (con_cero and prod.activo)
  ), o as (
    select m.*, case metrica when 'units' then u when 'revenue' then rev else gp end val from m
  ), k as (
    select o.*, row_number() over (order by case when orden = 'top' then -val else val end, nombre) rk,
           sum(val) over () total from o
  )
  select jsonb_agg(jsonb_build_object('rank', rk, 'sku', sku, 'name', nombre, 'category', cat, 'subcategory', subcat,
                                      'units', round(u, 0), 'revenue_usd', round(rev, 2), 'gross_profit_usd', round(gp, 2),
                                      'margin_pct', case when rev > 0 then round(gp / rev * 100, 1) end,
                                      'share_pct', case when total > 0 then round(val / total * 100, 1) end)
                   order by rk),
         max(total)::int
  into res, n from k where rk <= lim;

  return agente._sobre('get_top_products',
    jsonb_build_object('from', desde, 'to', hasta, 'metric', metrica, 'order', orden, 'limit', lim, 'category', v_cat,
                       'include_zero_sales', con_cero),
    desde, hasta,
    case when res is null then null else jsonb_build_object('items', res, 'criterion', metrica) end,
    array['revenue_usd', 'gross_profit_usd', 'margin_pct', 'share_pct'], array['units', 'rank']);
exception when others then
  if sqlstate = '57014' then raise; end if;
  declare h text; begin get stacked diagnostics h = pg_exception_hint; return agente._fallo('get_top_products', sqlstate, sqlerrm, h); end;
end $$;

-- 4. find_products -------------------------------------------------------------
create function agente.find_products(p jsonb default '{}') returns jsonb
language plpgsql stable security definer set search_path = agente, public, extensions, pg_temp as $$
declare q text; lim int; inactivos boolean; res jsonb; s1 numeric; s2 numeric; n int;
begin
  perform agente._claves(p, array['query', 'limit', 'include_inactive']);
  q := agente._texto(p, 'query', true, 2, 60);
  lim := agente._int(p, 'limit', 5, 1, 10);
  inactivos := agente._bool(p, 'include_inactive', false);

  with c as (
    select p.sku, p.nombre, pc.nombre || ' › ' || sc.nombre cat, p.activo,
           case when upper(p.sku) = upper(q) then 1.0
                else greatest(extensions.similarity(agente._norm(p.nombre), agente._norm(q)),
                              extensions.word_similarity(agente._norm(q), agente._norm(p.nombre)),
                              extensions.similarity(agente._norm(sc.nombre), agente._norm(q)) * 0.8) end sim
    from public.productos p join public.categorias sc on sc.id = p.categoria_id
    join public.categorias pc on pc.id = sc.categoria_padre_id
    where p.negocio_id = agente._neg() and (inactivos or p.activo)
  ), f as (
    select * from c where sim >= 0.3 order by sim desc, nombre limit lim
  )
  select jsonb_agg(jsonb_build_object('sku', sku, 'name', nombre, 'category', cat, 'active', activo, 'similarity', round(sim, 2))
                   order by sim desc, nombre),
         max(sim), count(*)
  into res, s1, n from f;
  select sim into s2 from (
    select greatest(extensions.similarity(agente._norm(p.nombre), agente._norm(q)),
                    extensions.word_similarity(agente._norm(q), agente._norm(p.nombre))) sim
    from public.productos p where p.negocio_id = agente._neg() and (inactivos or p.activo)
    order by 1 desc offset 1 limit 1) x;

  return agente._sobre('find_products', jsonb_build_object('query', q, 'limit', lim, 'include_inactive', inactivos),
    null, null,
    case when res is null then null
         else jsonb_build_object('matches', res,
                                 'ambiguous', n > 1 and s1 < 1 and s2 >= 0.35 and s1 - s2 < 0.15) end,
    array['similarity'], array['sku', 'name', 'active']);
exception when others then
  if sqlstate = '57014' then raise; end if;
  declare h text; begin get stacked diagnostics h = pg_exception_hint; return agente._fallo('find_products', sqlstate, sqlerrm, h); end;
end $$;

-- 5. get_product ---------------------------------------------------------------
create function agente.get_product(p jsonb default '{}') returns jsonb
language plpgsql stable security definer set search_path = agente, public, extensions, pg_temp as $$
declare v_sku text; r record; hist jsonb; pend jsonb; v_motivo text;
begin
  perform agente._claves(p, array['sku']);
  v_sku := upper(agente._texto(p, 'sku', true, 3, 20));
  select * into r from agente._productos() x where x.sku = v_sku;
  if r is null then perform agente._error('not_found', 'No encontré ningún producto con ese código.'); end if;

  select jsonb_agg(jsonb_build_object('from', (pr.vigente_desde at time zone 'America/Havana')::date,
                                      'to', (pr.vigente_hasta at time zone 'America/Havana')::date, 'price_usd', pr.precio_usd)
                   order by pr.vigente_desde)
  into hist from public.precios_producto pr where pr.producto_id = r.producto_id and pr.vigente_desde <= agente._ahora();

  select jsonb_agg(jsonb_build_object('ordered_at', (c.fecha at time zone 'America/Havana')::date, 'quantity', round(lc.cantidad),
                                      'supplier', pv.nombre, 'days_since_order', agente._hoy() - (c.fecha at time zone 'America/Havana')::date)
                   order by c.fecha)
  into pend from public.compras c join public.lineas_compra lc on lc.compra_id = c.id
  join public.proveedores pv on pv.id = c.proveedor_id
  where c.estado = 'pendiente' and lc.producto_id = r.producto_id;

  select d.motivo into v_motivo from public.devoluciones d join public.lineas_venta lv on lv.id = d.linea_venta_id
  where lv.producto_id = r.producto_id and d.fecha > agente._ahora() - interval '30 days' and d.fecha <= agente._ahora()
  group by d.motivo order by sum(d.cantidad) desc limit 1;

  return agente._sobre('get_product', jsonb_build_object('sku', v_sku), null, null, jsonb_build_object(
    'sku', r.sku, 'name', r.nombre, 'category', r.categoria, 'subcategory', r.subcategoria, 'line', r.linea,
    'active', r.activo, 'unit', 'unidad', 'priority', r.prioritario, 'abc_class', r.abc,
    'price_usd', r.precio_usd,
    'price_cup_today', case when r.precio_usd is not null then agente._cup(r.precio_usd, agente._tasa(agente._hoy())) end,
    'price_history', coalesce(hist, '[]'::jsonb),
    'stock', round(r.stock), 'min_stock', round(r.stock_minimo), 'status', r.estado,
    'days_out_of_stock', r.dias_sin_stock,
    'velocity_30d', r.velocidad, 'coverage_days', r.cobertura, 'lead_time_days', r.plazo_dias,
    'pending_purchases', coalesce(pend, '[]'::jsonb),
    'last_sale_at', agente._iso(r.ultima_venta),
    'sales_30d', jsonb_build_object('units', round(r.uds_30d), 'net_usd', r.net_usd_30d),
    'margin_30d_pct', r.margen_30d, 'avg_cost_usd', round(r.coste_medio, 2),
    'stock_value_usd', r.valor_stock,
    'returns_30d', jsonb_build_object('units', round(r.devueltas_30d),
                                      'return_pct', case when r.uds_30d > 0 then round(r.devueltas_30d / r.uds_30d * 100, 1) else 0 end,
                                      'top_reason', v_motivo),
    'slow_mover', r.baja_rotacion),
    array['price_cup_today', 'velocity_30d', 'coverage_days', 'margin_30d_pct', 'avg_cost_usd', 'stock_value_usd', 'return_pct', 'net_usd', 'abc_class', 'status', 'priority'],
    array['stock', 'min_stock', 'price_usd', 'price_history', 'pending_purchases', 'last_sale_at', 'units', 'days_out_of_stock', 'lead_time_days']);
exception when others then
  if sqlstate = '57014' then raise; end if;
  declare h text; begin get stacked diagnostics h = pg_exception_hint; return agente._fallo('get_product', sqlstate, sqlerrm, h); end;
end $$;

-- 6. get_product_history -------------------------------------------------------
create function agente.get_product_history(p jsonb default '{}') returns jsonb
language plpgsql stable security definer set search_path = agente, public, extensions, pg_temp as $$
declare v_sku text; desde date; hasta date; gran text; pid bigint; nom text; ini timestamptz; fin timestamptz; res jsonb; stock_ahora numeric;
begin
  perform agente._claves(p, array['sku', 'from', 'to', 'granularity']);
  v_sku := upper(agente._texto(p, 'sku', true, 3, 20));
  desde := agente._fecha(p, 'from', null); hasta := agente._fecha(p, 'to', null);
  perform agente._rango(desde, hasta);
  gran := agente._enum(p, 'granularity', array['day', 'week', 'month'], 'week');
  select id, nombre into pid, nom from public.productos where sku = v_sku and negocio_id = agente._neg();
  if pid is null then perform agente._error('not_found', 'No encontré ningún producto con ese código.'); end if;
  ini := agente._ts(desde); fin := agente._fin(hasta);
  select stock_actual into stock_ahora from public.inventario where producto_id = pid;

  with b as (
    select distinct agente._clave(gran, g, null, null) k
    from generate_series(ini, fin - interval '1 second', interval '1 day') g
  ), v as (
    select agente._clave(gran, v.fecha, null, null) k, sum(lv.cantidad) u, sum(lv.cantidad * lv.precio_unitario_usd) r
    from public.lineas_venta lv join public.ventas v on v.id = lv.venta_id
    where lv.producto_id = pid and v.estado = 'completada' and v.fecha >= ini and v.fecha < fin group by 1
  ), d as (
    select agente._clave(gran, d.fecha, null, null) k, sum(d.reembolso_usd) r
    from public.devoluciones d join public.lineas_venta lv on lv.id = d.linea_venta_id
    where lv.producto_id = pid and d.fecha >= ini and d.fecha < fin group by 1
  ), mv as (
    select agente._clave(gran, m.fecha, null, null) k,
           sum(m.cantidad) filter (where m.tipo = 'compra') compras, max(m.fecha) ultima
    from public.movimientos_inventario m where m.producto_id = pid and m.fecha >= ini and m.fecha < fin group by 1
  ), fin_bucket as (
    -- stock al final de cada tramo = stock actual − movimientos posteriores al tramo
    select b.k, stock_ahora - coalesce((
             select sum(m.cantidad) from public.movimientos_inventario m
             where m.producto_id = pid and agente._clave(gran, m.fecha, null, null) > b.k and m.fecha <= agente._ahora()), 0) s
    from b
  )
  select jsonb_agg(jsonb_build_object('period', b.k, 'units', round(coalesce(v.u, 0)),
                                      'net_usd', round(coalesce(v.r, 0) - coalesce(d.r, 0), 2),
                                      'avg_price_usd', case when v.u > 0 then round(v.r / v.u, 2) end,
                                      'stock_end', round(fb.s), 'purchases_received', round(coalesce(mv.compras, 0)))
                   order by b.k)
  into res
  from b left join v on v.k = b.k left join d on d.k = b.k left join mv on mv.k = b.k left join fin_bucket fb on fb.k = b.k;

  return agente._sobre('get_product_history', jsonb_build_object('sku', v_sku, 'from', desde, 'to', hasta, 'granularity', gran),
    desde, hasta, jsonb_build_object('sku', v_sku, 'name', nom, 'series', coalesce(res, '[]'::jsonb)),
    array['net_usd', 'avg_price_usd', 'stock_end'], array['units', 'purchases_received']);
exception when others then
  if sqlstate = '57014' then raise; end if;
  declare h text; begin get stacked diagnostics h = pg_exception_hint; return agente._fallo('get_product_history', sqlstate, sqlerrm, h); end;
end $$;

-- 7. get_inventory_status ------------------------------------------------------
create function agente.get_inventory_status(p jsonb default '{}') returns jsonb
language plpgsql stable security definer set search_path = agente, public, extensions, pg_temp as $$
declare filtro text; v_cat text; solo_prio boolean; lim int; estados text[]; res jsonb; tot jsonb;
begin
  perform agente._claves(p, array['filter', 'category', 'priority_only', 'limit']);
  filtro := agente._enum(p, 'filter', array['all_issues', 'out_of_stock', 'low_stock', 'stockout_risk', 'overstock', 'no_movement'], 'all_issues');
  v_cat := agente._texto(p, 'category', false, 2, 60);
  solo_prio := agente._bool(p, 'priority_only', false);
  lim := agente._int(p, 'limit', agente._p('max_limit')::int, 1, agente._p('max_limit')::int);
  estados := case filtro
    when 'out_of_stock' then array['agotado']
    when 'low_stock' then array['stock_bajo']
    when 'stockout_risk' then array['riesgo_rotura']
    when 'overstock' then array['exceso']
    when 'no_movement' then array['sin_movimiento']
    else array['agotado', 'riesgo_rotura', 'stock_bajo', 'exceso', 'sin_movimiento'] end;

  select jsonb_agg(x.j order by x.o1, x.o2 desc, x.o3) into res from (
    select jsonb_build_object('sku', sku, 'name', nombre, 'category', categoria, 'priority', prioritario, 'status', estado,
                              'stock', round(stock), 'min_stock', round(stock_minimo), 'velocity_30d', velocidad,
                              'coverage_days', cobertura, 'lead_time_days', plazo_dias, 'pending_qty', round(pendiente),
                              'stock_value_usd', valor_stock, 'days_out_of_stock', dias_sin_stock) j,
           array_position(array['agotado', 'riesgo_rotura', 'stock_bajo', 'exceso', 'sin_movimiento'], estado) o1,
           prioritario o2, coalesce(cobertura, 0) o3
    from agente._productos() i
    where activo and estado = any (estados) and (not solo_prio or prioritario)
      and (v_cat is null or agente._norm(categoria) = agente._norm(v_cat) or agente._norm(subcategoria) = agente._norm(v_cat))
    order by 2, 3 desc, 4 limit lim) x;

  select jsonb_build_object(
    'by_status', jsonb_build_object(
      'agotado', count(*) filter (where estado = 'agotado'), 'riesgo_rotura', count(*) filter (where estado = 'riesgo_rotura'),
      'stock_bajo', count(*) filter (where estado = 'stock_bajo'), 'exceso', count(*) filter (where estado = 'exceso'),
      'sin_movimiento', count(*) filter (where estado = 'sin_movimiento')),
    'immobilized_value_usd', round(coalesce(sum(valor_stock) filter (where estado in ('exceso', 'sin_movimiento')), 0), 2),
    'total_stock_value_usd', round(coalesce(sum(valor_stock), 0), 2),
    'inactive_stock_value_usd', round(coalesce(sum(valor_stock) filter (where not activo), 0), 2))
  into tot from agente._productos() i where activo or stock > 0;

  return agente._sobre('get_inventory_status',
    jsonb_build_object('filter', filtro, 'category', v_cat, 'priority_only', solo_prio, 'limit', lim), null, null,
    jsonb_build_object('items', coalesce(res, '[]'::jsonb), 'totals', tot),
    array['velocity_30d', 'coverage_days', 'stock_value_usd', 'immobilized_value_usd', 'total_stock_value_usd', 'status', 'priority'],
    array['stock', 'min_stock', 'pending_qty', 'lead_time_days', 'days_out_of_stock']);
exception when others then
  if sqlstate = '57014' then raise; end if;
  declare h text; begin get stacked diagnostics h = pg_exception_hint; return agente._fallo('get_inventory_status', sqlstate, sqlerrm, h); end;
end $$;

-- 8. get_margin_analysis -------------------------------------------------------
create function agente.get_margin_analysis(p jsonb default '{}') returns jsonb
language plpgsql stable security definer set search_path = agente, public, extensions, pg_temp as $$
declare desde date; hasta date; agrupar text; umbral numeric; lim int; orden text; ini timestamptz; fin timestamptz;
        c_ini timestamptz; res jsonb; v_global numeric;
begin
  perform agente._claves(p, array['from', 'to', 'group_by', 'below_threshold_pct', 'limit', 'order']);
  desde := agente._fecha(p, 'from', null); hasta := agente._fecha(p, 'to', null);
  perform agente._rango(desde, hasta);
  agrupar := agente._enum(p, 'group_by', array['product', 'category'], 'category');
  umbral := agente._num(p, 'below_threshold_pct');
  lim := agente._int(p, 'limit', 20, 1, agente._p('max_limit')::int);
  orden := agente._enum(p, 'order', array['asc', 'desc'], 'asc');
  ini := agente._ts(desde); fin := agente._fin(hasta); c_ini := ini - (fin - ini);

  with l as (
    select case when agrupar = 'product' then p.sku else pc.nombre end k,
           case when agrupar = 'product' then p.nombre else pc.nombre end nom,
           v.fecha >= ini actual, lv.cantidad c, lv.cantidad * lv.precio_unitario_usd r, lv.cantidad * lv.coste_unitario_usd co
    from public.lineas_venta lv join public.ventas v on v.id = lv.venta_id
    join public.productos p on p.id = lv.producto_id join public.categorias sc on sc.id = p.categoria_id
    join public.categorias pc on pc.id = sc.categoria_padre_id
    where v.estado = 'completada' and v.negocio_id = agente._neg() and v.fecha >= c_ini and v.fecha < fin
  ), dv as (
    select case when agrupar = 'product' then p.sku else pc.nombre end k, sum(d.reembolso_usd) r,
           sum(case when d.reingresa_stock then d.cantidad * lv.coste_unitario_usd else 0 end) co
    from public.devoluciones d join public.lineas_venta lv on lv.id = d.linea_venta_id
    join public.productos p on p.id = lv.producto_id join public.categorias sc on sc.id = p.categoria_id
    join public.categorias pc on pc.id = sc.categoria_padre_id
    where d.fecha >= ini and d.fecha < fin group by 1
  ), a as (
    select l.k, max(l.nom) nom,
           sum(c) filter (where actual) u,
           sum(r) filter (where actual) - coalesce(max(dv.r), 0) net,
           sum(co) filter (where actual) - coalesce(max(dv.co), 0) cogs,
           sum(r) filter (where not actual) net_p, sum(co) filter (where not actual) cogs_p,
           sum(co) filter (where actual) / nullif(sum(c) filter (where actual), 0) cu,
           sum(co) filter (where not actual) / nullif(sum(c) filter (where not actual), 0) cu_p,
           sum(r) filter (where actual) / nullif(sum(c) filter (where actual), 0) pu,
           sum(r) filter (where not actual) / nullif(sum(c) filter (where not actual), 0) pu_p
    from l left join dv on dv.k = l.k group by l.k
  ), m as (
    select *, case when net > 0 then round((net - cogs) / net * 100, 1) end mg,
           case when net_p > 0 then round((net_p - cogs_p) / net_p * 100, 1) end mg_p
    from a where net is not null
  )
  select jsonb_agg(jsonb_build_object('key', k, 'name', nom, 'units', round(u), 'net_usd', round(net, 2), 'cogs_usd', round(cogs, 2),
                                      'gross_profit_usd', round(net - cogs, 2), 'margin_pct', mg, 'margin_prev_period_pct', mg_p,
                                      'avg_cost_change_pct', agente._pct(cu, cu_p), 'price_change_pct', agente._pct(pu, pu_p))
                   order by case when orden = 'asc' then mg else -mg end, k)
  into res from (
    select * from m
    where (umbral is null or (mg < umbral and (agrupar = 'category' or u >= agente._p('margen_min_unidades'))))
    order by case when orden = 'asc' then mg else -mg end, k limit lim) s;

  select round((sum(net) - sum(cogs)) / nullif(sum(net), 0) * 100, 1) into v_global
  from (select (agente._totales(ini, fin, 'all') ->> 'net_usd')::numeric net,
               (agente._totales(ini, fin, 'all') ->> 'cogs_usd')::numeric cogs) t;

  return agente._sobre('get_margin_analysis',
    jsonb_build_object('from', desde, 'to', hasta, 'group_by', agrupar, 'below_threshold_pct', umbral, 'limit', lim, 'order', orden),
    desde, hasta, jsonb_build_object('items', coalesce(res, '[]'::jsonb), 'overall_margin_pct', v_global),
    array['net_usd', 'cogs_usd', 'gross_profit_usd', 'margin_pct', 'margin_prev_period_pct', 'avg_cost_change_pct', 'price_change_pct', 'overall_margin_pct'],
    array['units']);
exception when others then
  if sqlstate = '57014' then raise; end if;
  declare h text; begin get stacked diagnostics h = pg_exception_hint; return agente._fallo('get_margin_analysis', sqlstate, sqlerrm, h); end;
end $$;

-- 9. get_alerts ----------------------------------------------------------------
create function agente.get_alerts(p jsonb default '{}') returns jsonb
language plpgsql stable security definer set search_path = agente, public, extensions, pg_temp as $$
declare prio text; cat text;
begin
  perform agente._claves(p, array['min_priority', 'category']);
  prio := agente._enum(p, 'min_priority', array['low', 'medium', 'high', 'urgent'], 'low');
  cat := agente._enum(p, 'category', array['ventas', 'inventario', 'rentabilidad', 'devoluciones', 'anulaciones', 'tasa', 'calidad_datos'], null);
  return agente._sobre('get_alerts', jsonb_build_object('min_priority', prio, 'category', cat), null, null,
    agente._alertas_json(prio, cat), array['alerts', 'current_value'], array['count_by_priority']);
exception when others then
  if sqlstate = '57014' then raise; end if;
  declare h text; begin get stacked diagnostics h = pg_exception_hint; return agente._fallo('get_alerts', sqlstate, sqlerrm, h); end;
end $$;

-- 10. get_returns_and_voids ----------------------------------------------------
create function agente.get_returns_and_voids(p jsonb default '{}') returns jsonb
language plpgsql stable security definer set search_path = agente, public, extensions, pg_temp as $$
declare desde date; hasta date; agrupar text; ini timestamptz; fin timestamptz; anul jsonb; dev jsonb;
begin
  perform agente._claves(p, array['from', 'to', 'group_by']);
  desde := agente._fecha(p, 'from', null); hasta := agente._fecha(p, 'to', null);
  perform agente._rango(desde, hasta);
  agrupar := agente._enum(p, 'group_by', array['product', 'reason', 'day'], 'product');
  ini := agente._ts(desde); fin := agente._fin(hasta);

  with v as (
    select * from public.ventas where negocio_id = agente._neg() and fecha >= ini and fecha < fin
  )
  select jsonb_build_object(
    'count', count(*) filter (where estado = 'anulada'),
    'total_tickets', count(*),
    'pct_of_tickets', round(count(*) filter (where estado = 'anulada')::numeric / nullif(count(*), 0) * 100, 1),
    'amount_usd', round(coalesce(sum(total_usd) filter (where estado = 'anulada'), 0), 2),
    'by_reason', coalesce((select jsonb_agg(jsonb_build_object('reason', motivo_anulacion, 'count', n) order by n desc)
                           from (select motivo_anulacion, count(*) n from v where estado = 'anulada' group by 1) x), '[]'::jsonb),
    'by_channel', coalesce((select jsonb_agg(jsonb_build_object('channel', canal, 'count', n, 'pct', pct) order by canal)
                            from (select canal, count(*) filter (where estado = 'anulada') n,
                                         round(count(*) filter (where estado = 'anulada')::numeric / count(*) * 100, 1) pct
                                  from v group by 1) x), '[]'::jsonb),
    'by_day', case when agrupar = 'day' then coalesce((
        select jsonb_agg(jsonb_build_object('date', dia, 'count', n, 'pct', pct) order by dia)
        from (select (fecha at time zone 'America/Havana')::date dia, count(*) filter (where estado = 'anulada') n,
                     round(count(*) filter (where estado = 'anulada')::numeric / count(*) * 100, 1) pct
              from v group by 1) x), '[]'::jsonb) end)
  into anul from v;

  with d as (
    select d.*, p.sku, p.nombre, lv.producto_id from public.devoluciones d
    join public.lineas_venta lv on lv.id = d.linea_venta_id join public.productos p on p.id = lv.producto_id
    where p.negocio_id = agente._neg() and d.fecha >= ini and d.fecha < fin
  ), vend as (
    select lv.producto_id, sum(lv.cantidad) u from public.lineas_venta lv join public.ventas v on v.id = lv.venta_id
    where v.estado = 'completada' and v.negocio_id = agente._neg() and v.fecha >= ini and v.fecha < fin group by 1
  )
  select jsonb_build_object(
    'units', round(coalesce(sum(cantidad), 0)),
    'amount_usd', round(coalesce(sum(reembolso_usd), 0), 2),
    'restocked_units', round(coalesce(sum(cantidad) filter (where reingresa_stock), 0)),
    'by_product', coalesce((
        select jsonb_agg(jsonb_build_object('sku', sku, 'name', nombre, 'returned_units', round(n), 'sold_units', round(u),
                                            'return_pct', case when u > 0 then round(n / u * 100, 1) end,
                                            'top_reason', motivo, 'restocked_units', round(rs))
                         order by n desc, nombre)
        from (select d.sku, d.nombre, sum(d.cantidad) n, max(vend.u) u, sum(d.cantidad) filter (where d.reingresa_stock) rs,
                     mode() within group (order by d.motivo) motivo
              from d left join vend on vend.producto_id = d.producto_id group by 1, 2 limit 50) x), '[]'::jsonb),
    'by_reason', coalesce((select jsonb_agg(jsonb_build_object('reason', motivo, 'units', round(n)) order by n desc)
                           from (select motivo, sum(cantidad) n from d group by 1) x), '[]'::jsonb))
  into dev from d;

  return agente._sobre('get_returns_and_voids', jsonb_build_object('from', desde, 'to', hasta, 'group_by', agrupar),
    desde, hasta, jsonb_build_object('voids', anul, 'returns', dev),
    array['pct_of_tickets', 'return_pct', 'pct'], array['count', 'total_tickets', 'amount_usd', 'units', 'returned_units', 'sold_units']);
exception when others then
  if sqlstate = '57014' then raise; end if;
  declare h text; begin get stacked diagnostics h = pg_exception_hint; return agente._fallo('get_returns_and_voids', sqlstate, sqlerrm, h); end;
end $$;

-- 11. get_exchange_rate --------------------------------------------------------
create function agente.get_exchange_rate(p jsonb default '{}') returns jsonb
language plpgsql stable security definer set search_path = agente, public, extensions, pg_temp as $$
declare desde date; hasta date; hoy date := agente._hoy(); t_hoy numeric; t_ini numeric; serie jsonb;
begin
  perform agente._claves(p, array['from', 'to']);
  desde := agente._fecha(p, 'from', hoy - 29); hasta := agente._fecha(p, 'to', hoy);
  perform agente._rango(desde, hasta);
  if hasta > hoy then hasta := hoy; end if;
  t_hoy := agente._tasa(hoy); t_ini := agente._tasa(desde);
  select jsonb_agg(jsonb_build_object('date', fecha, 'usd_cup', usd_cup) order by fecha) into serie
  from public.tasas_cambio where fecha between desde and hasta;

  return agente._sobre('get_exchange_rate', jsonb_build_object('from', desde, 'to', hasta), desde, hasta, jsonb_build_object(
    'today', jsonb_build_object('date', (select max(fecha) from public.tasas_cambio where fecha <= hoy), 'usd_cup', t_hoy, 'source', 'elTOQUE'),
    'series', coalesce(serie, '[]'::jsonb),
    'min', (select min(usd_cup) from public.tasas_cambio where fecha between desde and hasta),
    'max', (select max(usd_cup) from public.tasas_cambio where fecha between desde and hasta),
    'change_pct', jsonb_build_object('d7', agente._pct(t_hoy, agente._tasa(hoy - 7)), 'd30', agente._pct(t_hoy, agente._tasa(hoy - 30)),
                                     'period', agente._pct(agente._tasa(hasta), t_ini), 'year', agente._pct(t_hoy, agente._tasa(hoy - 365))),
    'impact', jsonb_build_object('example_price_usd', 10.00, 'price_cup_start', agente._cup(10, t_ini),
                                 'price_cup_today', agente._cup(10, t_hoy),
                                 'note', 'Los precios están fijados en USD: si sube la tasa, todo el catálogo se encarece en CUP; el margen en USD no cambia.')),
    array['change_pct', 'price_cup_start', 'price_cup_today'], array['usd_cup', 'series', 'min', 'max']);
exception when others then
  if sqlstate = '57014' then raise; end if;
  declare h text; begin get stacked diagnostics h = pg_exception_hint; return agente._fallo('get_exchange_rate', sqlstate, sqlerrm, h); end;
end $$;

-- 12. get_data_quality ---------------------------------------------------------
create function agente.get_data_quality(p jsonb default '{}') returns jsonb
language plpgsql stable security definer set search_path = agente, public, extensions, pg_temp as $$
declare ahora timestamptz := agente._ahora(); u_venta timestamptz; u_mov timestamptz; res jsonb;
begin
  perform agente._claves(p, array[]::text[]);
  select max(fecha) into u_venta from public.ventas where negocio_id = agente._neg() and fecha <= ahora;
  select max(fecha) into u_mov from public.movimientos_inventario where fecha <= ahora;

  with prod as (select * from agente._productos())
  select jsonb_build_object(
    'last_sale_at', agente._iso(u_venta), 'last_movement_at', agente._iso(u_mov),
    'freshness_minutes', round(extract(epoch from ahora - u_venta) / 60),
    'store_open_now', agente._abierto(ahora),
    'fx_last_date', (select max(fecha) from public.tasas_cambio where fecha <= agente._hoy()),
    'fx_missing_today', not exists (select 1 from public.tasas_cambio where fecha = agente._hoy()),
    'active_without_price', coalesce((select jsonb_agg(jsonb_build_object('sku', sku, 'name', nombre, 'stock', round(stock)) order by sku)
                                      from prod where activo and precio_usd is null), '[]'::jsonb),
    'inactive_with_stock', coalesce((select jsonb_agg(jsonb_build_object('sku', sku, 'name', nombre, 'stock', round(stock)) order by sku)
                                     from prod where not activo and stock > 0), '[]'::jsonb),
    'products_without_min_stock', coalesce((select jsonb_agg(jsonb_build_object('sku', sku, 'name', nombre) order by sku)
                                            from prod where activo and stock_minimo = 0), '[]'::jsonb),
    'stock_mismatch_count', (select count(*) from public.inventario i
                             join (select producto_id, sum(cantidad) s from public.movimientos_inventario group by 1) m using (producto_id)
                             where i.stock_actual <> m.s),
    'overdue_purchases', coalesce((select jsonb_agg(jsonb_build_object('supplier', split_part(a.titulo, 'Compra retrasada de ', 2),
                                                                       'days_since_order', a.valor_actual, 'usual_days', a.umbral))
                                   from agente._alertas() a where a.regla = 'compra_retrasada'), '[]'::jsonb))
  into res;

  return agente._sobre('get_data_quality', '{}'::jsonb, null, null, res,
    array['freshness_minutes'], array['last_sale_at', 'last_movement_at', 'active_without_price', 'inactive_with_stock', 'stock_mismatch_count']);
exception when others then
  if sqlstate = '57014' then raise; end if;
  declare h text; begin get stacked diagnostics h = pg_exception_hint; return agente._fallo('get_data_quality', sqlstate, sqlerrm, h); end;
end $$;
