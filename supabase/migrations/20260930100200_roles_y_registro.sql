-- Roles, permisos y registro del Agente Interno (06_politica_de_seguridad.md).
--   agente_owner    : propietario de las funciones de `agente`; solo SELECT sobre `public`. Sin login.
--   agente_lectura  : el que usa el servicio para las herramientas. Solo EXECUTE sobre las 12 funciones.
--   agente_registro : el que usa el servicio para escribir el registro. Solo el esquema `registro`.
-- Los roles se crean sin login. Para activarlos (fuera del repositorio, nunca en el chat):
--   alter role agente_lectura  with login password '<secreto>';
--   alter role agente_registro with login password '<secreto>';

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'agente_owner') then create role agente_owner nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'agente_lectura') then create role agente_lectura nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'agente_registro') then create role agente_registro nologin; end if;
end $$;

grant agente_owner to current_user;   -- necesario para asignarle la propiedad de las funciones

-- agente_owner: lectura de los datos del negocio -----------------------------
grant usage on schema public, agente, extensions to agente_owner;
grant select on all tables in schema public to agente_owner;
grant select on agente.parametros, agente.config_categoria to agente_owner;

-- Las tablas de public tienen RLS activado: política explícita de solo lectura para agente_owner.
do $$
declare t text;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('drop policy if exists agente_owner_lectura on public.%I', t);
    execute format('create policy agente_owner_lectura on public.%I for select to agente_owner using (true)', t);
  end loop;
end $$;

-- Funciones: nadie las ejecuta por defecto.
revoke execute on all functions in schema agente from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on schema agente from anon, authenticated';
    execute 'revoke execute on all functions in schema agente from anon, authenticated';
  end if;
end $$;
grant execute on all functions in schema agente to agente_owner;

-- Las 12 herramientas pertenecen a agente_owner (SECURITY DEFINER).
alter function agente.get_business_summary(jsonb) owner to agente_owner;
alter function agente.get_sales_summary(jsonb) owner to agente_owner;
alter function agente.get_top_products(jsonb) owner to agente_owner;
alter function agente.find_products(jsonb) owner to agente_owner;
alter function agente.get_product(jsonb) owner to agente_owner;
alter function agente.get_product_history(jsonb) owner to agente_owner;
alter function agente.get_inventory_status(jsonb) owner to agente_owner;
alter function agente.get_margin_analysis(jsonb) owner to agente_owner;
alter function agente.get_alerts(jsonb) owner to agente_owner;
alter function agente.get_returns_and_voids(jsonb) owner to agente_owner;
alter function agente.get_exchange_rate(jsonb) owner to agente_owner;
alter function agente.get_data_quality(jsonb) owner to agente_owner;

-- agente_lectura: solo las 12 herramientas ----------------------------------
grant usage on schema agente to agente_lectura;
grant execute on function
  agente.get_business_summary(jsonb), agente.get_sales_summary(jsonb), agente.get_top_products(jsonb),
  agente.find_products(jsonb), agente.get_product(jsonb), agente.get_product_history(jsonb),
  agente.get_inventory_status(jsonb), agente.get_margin_analysis(jsonb), agente.get_alerts(jsonb),
  agente.get_returns_and_voids(jsonb), agente.get_exchange_rate(jsonb), agente.get_data_quality(jsonb)
to agente_lectura;
alter role agente_lectura set default_transaction_read_only = on;
alter role agente_lectura set statement_timeout = '10s';
alter role agente_lectura set idle_in_transaction_session_timeout = '30s';
alter role agente_lectura set search_path = agente;

-- Registro -------------------------------------------------------------------
create schema if not exists registro;

create table registro.interacciones (
  id           bigint generated always as identity primary key,
  fecha_hora   timestamptz not null default now(),
  canal        text not null check (canal in ('telegram', 'orquestador', 'planificador')),
  usuario_id   text,
  autorizado   boolean not null,
  entrada      text,
  herramientas jsonb not null default '[]',   -- [{name, params, rows, status, ms}]
  latencia_ms  int,
  tokens       jsonb,
  respuesta    text,
  estado       text not null,                 -- ok | error | rechazado | limite
  error        text
);
create index on registro.interacciones (fecha_hora);
create index on registro.interacciones (usuario_id, fecha_hora);

create table registro.alertas_enviadas (
  alert_key         text not null,
  regla             text not null,
  prioridad         text not null,
  fecha_deteccion   timestamptz not null,
  fecha_envio       timestamptz,               -- null = pendiente (silencio nocturno o límite diario)
  canal             text not null default 'telegram',
  primary key (alert_key, fecha_deteccion)
);
create index on registro.alertas_enviadas (fecha_envio);

create table registro.accesos_denegados (
  id               bigint generated always as identity primary key,
  fecha_hora       timestamptz not null default now(),
  telegram_user_id text,
  chat_type        text,
  texto            text
);

create table registro.preguntas_sin_herramienta (
  id         bigint generated always as identity primary key,
  fecha_hora timestamptz not null default now(),
  pregunta   text not null
);

create function registro.purgar(dias int default 90) returns void language sql as $$
  delete from registro.interacciones where fecha_hora < now() - dias * interval '1 day';
  delete from registro.alertas_enviadas where fecha_deteccion < now() - dias * interval '1 day';
  delete from registro.accesos_denegados where fecha_hora < now() - dias * interval '1 day';
  delete from registro.preguntas_sin_herramienta where fecha_hora < now() - dias * interval '1 day';
$$;

revoke all on schema registro from public;
revoke execute on function registro.purgar(int) from public;
grant usage on schema registro to agente_registro;
grant select, insert, update, delete on all tables in schema registro to agente_registro;
grant execute on function registro.purgar(int) to agente_registro;
alter role agente_registro set statement_timeout = '10s';
alter role agente_registro set search_path = registro;
