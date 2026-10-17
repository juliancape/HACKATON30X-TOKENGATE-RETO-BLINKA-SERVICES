-- Esquema inicial MVP: conversaciones, solicitudes, decisiones, historico de precios,
-- politicas y auditoria. Ejecutar en Supabase (SQL Editor).

create table if not exists conversations (
    id text primary key,
    estado text not null default 'nueva',
    contexto jsonb not null default '{}'::jsonb,
    creado_en timestamptz not null default now(),
    actualizado_en timestamptz not null default now()
);

create table if not exists purchase_requests (
    solicitud_id uuid primary key default gen_random_uuid(),
    conversacion_id text not null references conversations(id),
    telefono_empleado text not null,
    estado text not null default 'nueva',
    requisitos jsonb,
    total_cop integer,
    creado_en timestamptz not null default now(),
    actualizado_en timestamptz not null default now()
);

create index if not exists idx_pr_telefono_estado on purchase_requests (telefono_empleado, estado);

create table if not exists decisions (
    id uuid primary key default gen_random_uuid(),
    solicitud_id uuid not null references purchase_requests(solicitud_id),
    opcion_id text not null,
    decision text not null check (decision in ('aprobar', 'rechazar', 'escalar')),
    motivo text not null,
    precio_historico_promedio_cop integer,
    desviacion_pct numeric,
    violaciones_politica jsonb default '[]'::jsonb,
    creado_en timestamptz not null default now()
);

create table if not exists price_history (
    id bigint generated always as identity primary key,
    producto_nombre text not null,
    tienda_nombre text,
    precio_cop integer not null,
    fecha timestamptz not null default now()
);

create index if not exists idx_ph_producto on price_history (producto_nombre);

create table if not exists policies (
    id bigint generated always as identity primary key,
    nombre text not null,
    descripcion text,
    regla jsonb not null,
    activa boolean not null default true,
    creado_en timestamptz not null default now()
);

insert into policies (nombre, descripcion, regla) values
    ('max_por_pedido', 'Tope de gasto por pedido en COP', '{"max_order_cop": 60000}'),
    ('max_diario', 'Tope de gasto diario por empleado en COP', '{"max_daily_cop": 120000}')
on conflict do nothing;

create table if not exists audit_events (
    id bigint generated always as identity primary key,
    conversacion_id text not null,
    evento text not null,
    detalle jsonb not null default '{}'::jsonb,
    creado_en timestamptz not null default now()
);

create index if not exists idx_ae_conv on audit_events (conversacion_id);
