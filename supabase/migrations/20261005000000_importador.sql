-- Rol del importador de datos del negocio (agente_interno/importador).
-- Escribe solo las tablas del negocio y la configuración de categorías; no ve el registro ni ejecuta herramientas.
-- Se crea sin login. Para activarlo (fuera del repositorio, nunca en el chat):
--   alter role agente_importador with login password '<secreto>';

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'agente_importador') then create role agente_importador nologin; end if;
end $$;

grant usage on schema public, agente to agente_importador;
grant select, insert, update, delete on
  public.categorias, public.productos, public.precios_producto, public.proveedores, public.compras,
  public.lineas_compra, public.inventario, public.movimientos_inventario, public.ventas, public.lineas_venta,
  public.pagos, public.devoluciones
to agente_importador;
grant select, insert on public.negocios to agente_importador;
grant select, insert, update on public.tasas_cambio to agente_importador;
grant usage on all sequences in schema public to agente_importador;
grant select, insert, update on agente.config_categoria to agente_importador;

-- Las tablas de public tienen RLS: política explícita para el importador.
do $$
declare t text;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = t and policyname = 'agente_importador_escritura') then
      execute format('create policy agente_importador_escritura on public.%I for all to agente_importador using (true) with check (true)', t);
    end if;
  end loop;
end $$;

alter role agente_importador set statement_timeout = '10min';
alter role agente_importador set search_path = public;
