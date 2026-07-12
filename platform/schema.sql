-- ExpertCarCheck — 3D Vehicle Platform · catalogue schema (Phase 1)
-- Postgres / Supabase. Run in the SQL editor of the project that serves the app.
-- Normalised so one base 3D asset + one render set serves many sellable variants,
-- and any decoded vehicle resolves to an asset in a single indexed lookup.

create extension if not exists "pgcrypto";

-- ── catalogue ─────────────────────────────────────────────────────────────
create table if not exists manufacturers (
  id      uuid primary key default gen_random_uuid(),
  name    text not null,
  slug    text not null unique
);

create table if not exists models (
  id              uuid primary key default gen_random_uuid(),
  manufacturer_id uuid not null references manufacturers(id) on delete cascade,
  name            text not null,
  slug            text not null,
  unique (manufacturer_id, slug)
);

create table if not exists generations (
  id          uuid primary key default gen_random_uuid(),
  model_id    uuid not null references models(id) on delete cascade,
  code        text,                       -- e.g. "8V", "F56", "AW"
  year_from   int  not null,
  year_to     int,                        -- null = current
  body_styles text[] default '{}'
);

create table if not exists engines (
  id             uuid primary key default gen_random_uuid(),
  code           text,
  fuel           text,                    -- petrol / diesel / hybrid / ev
  displacement_cc int,
  power_bhp      int,
  cylinders      int
);

create table if not exists trims (
  id            uuid primary key default gen_random_uuid(),
  generation_id uuid not null references generations(id) on delete cascade,
  name          text not null,            -- "SE", "S line", "Cooper S", "GTI"
  engine_id     uuid references engines(id),
  transmission  text,                     -- manual / auto
  drive         text                      -- fwd / rwd / awd
);

create table if not exists colours (
  id        uuid primary key default gen_random_uuid(),
  name      text not null,
  dvla_name text,                         -- how DVLA reports it (for matching)
  hex       text not null,
  finish    text default 'solid'          -- solid / metallic / pearl
);

create table if not exists wheels (
  id          uuid primary key default gen_random_uuid(),
  name        text,
  diameter_in int,
  style       text,
  asset_id    uuid                        -- optional separate wheel GLB
);

-- ── assets ────────────────────────────────────────────────────────────────
create table if not exists licences (
  id                  uuid primary key default gen_random_uuid(),
  type                text not null,      -- cc-by / cc0 / commercial / owned / editorial
  holder              text,
  terms               text,
  commercial_ok       boolean default false,
  attribution_required boolean default false
);

create table if not exists assets_3d (
  id           uuid primary key default gen_random_uuid(),
  tier         text not null default 'B', -- 'A' interactive / 'B' cinematic shell
  glb_url      text,                      -- base geometry (Draco/KTX2)
  poly_count   int,
  material_map jsonb,                     -- {body: "...", glass: "...", wheels:[...]}
  content_hash text unique,               -- dedup: identical geometry stored once
  licence_id   uuid references licences(id),
  status       text not null default 'draft'  -- draft / approved / rejected
);

create table if not exists render_sets (
  id          uuid primary key default gen_random_uuid(),
  asset_id    uuid not null references assets_3d(id) on delete cascade,
  colour_id   uuid references colours(id),
  colour_key  text not null default 'native',
  env         text not null default 'studio',
  frame_count int  not null,
  manifest_url text not null             -- JSON manifest of frame URLs
);

create table if not exists specifications (
  id         uuid primary key default gen_random_uuid(),
  trim_id    uuid references trims(id) on delete cascade,
  length_mm  int, width_mm int, height_mm int,
  doors      int, seats int,
  extra      jsonb
);

-- ── the sellable unit ─────────────────────────────────────────────────────
create table if not exists variants (
  id            uuid primary key default gen_random_uuid(),
  trim_id       uuid references trims(id),
  colour_id     uuid references colours(id),
  wheel_id      uuid references wheels(id),
  body_style    text,
  base_asset_id uuid references assets_3d(id),
  render_set_id uuid references render_sets(id)
);

-- NOTE: we deliberately do NOT index or store the vehicle registration (VRM).
-- The reg is personal data and is only ever a transient input: the app decodes
-- it to make/model/trim/colour/fuel and the catalogue is keyed on those vehicle
-- attributes. Nothing here is keyed on the plate.

-- ── indexes for millisecond lookup ────────────────────────────────────────
create index if not exists idx_models_mfr        on models(manufacturer_id);
create index if not exists idx_generations_model  on generations(model_id);
create index if not exists idx_trims_generation   on trims(generation_id);
create index if not exists idx_variants_lookup    on variants(trim_id, colour_id, wheel_id);
create index if not exists idx_render_sets_asset  on render_sets(asset_id, colour_key);

-- flattened resolver: one row per variant with everything the viewer needs
create materialized view if not exists variant_resolved as
select
  v.id                as variant_id,
  mf.slug             as make,
  m.slug              as model,
  g.code              as generation,
  g.year_from, g.year_to,
  t.name              as trim,
  e.fuel, e.power_bhp,
  v.body_style,
  c.dvla_name         as colour,
  c.hex               as colour_hex,
  a.tier,
  a.glb_url,
  rs.env,
  rs.frame_count,
  rs.manifest_url
from variants v
  join trims t         on t.id = v.trim_id
  join generations g   on g.id = t.generation_id
  join models m        on m.id = g.model_id
  join manufacturers mf on mf.id = m.manufacturer_id
  left join engines e  on e.id = t.engine_id
  left join colours c  on c.id = v.colour_id
  left join assets_3d a on a.id = v.base_asset_id
  left join render_sets rs on rs.id = v.render_set_id;

create index if not exists idx_vr_make_model on variant_resolved(make, model, year_from);

-- ── row-level security: catalogue is world-readable, writes service-role only
alter table variants enable row level security;
do $$ begin
  if not exists (select 1 from pg_policies where tablename='variants' and policyname='read_all') then
    create policy read_all on variants for select using (true);
  end if;
end $$;
