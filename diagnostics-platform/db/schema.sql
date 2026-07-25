-- ============================================================================
-- Expert Car Check — Diagnostics & Coding Platform
-- Supabase / Postgres schema  (Layer 2 storage + Layer 3 vector index)
-- ----------------------------------------------------------------------------
-- Run:  psql "$SUPABASE_DB_URL" -f db/schema.sql
-- ============================================================================

create extension if not exists "uuid-ossp";
create extension if not exists vector;      -- pgvector, for the AI/RAG layer

-- ----------------------------------------------------------------------------
-- VEHICLE PROFILES  — drives the transport layer (CAN vs CAN-FD, addressing)
-- ----------------------------------------------------------------------------
create table if not exists platform (
    id            uuid primary key default uuid_generate_v4(),
    make          text not null,                       -- 'BMW', 'VAG'
    family        text not null,                       -- 'F-series', 'G-series', 'MQB', 'MQB-Evo', 'MEB'
    year_from     int,
    year_to       int,
    bus           text not null check (bus in ('can', 'canfd')),
    can_bitrate   int  not null default 500000,        -- arbitration bitrate
    canfd_data_bitrate int,                            -- null for classic CAN
    transport     text not null default 'isotp'        -- 'isotp' | 'doip'
                  check (transport in ('isotp', 'doip')),
    sfd_locked    boolean not null default false,      -- VW 2020+ etc.
    secure_gateway boolean not null default false,
    notes         text
);

-- A specific control unit on a platform, with its diagnostic addressing.
create table if not exists ecu (
    id            uuid primary key default uuid_generate_v4(),
    platform_id   uuid not null references platform(id) on delete cascade,
    key           text not null,                       -- 'FEM_BODY', 'DDE_ENGINE', 'ABS_DSC', '09_CENTRAL_ELECTRICS'
    name          text not null,                       -- human name
    req_id        int  not null,                       -- ISO-TP request (tester→ECU) CAN id
    resp_id       int  not null,                       -- ISO-TP response (ECU→tester) CAN id
    addressing    text not null default 'physical'
                  check (addressing in ('physical', 'functional')),
    safety_critical boolean not null default false,    -- airbag/ABS actuator etc.
    unique (platform_id, key)
);

-- ----------------------------------------------------------------------------
-- CODING DEFINITIONS  — the moat. One row = one programmable feature.
-- Model covers both BMW FDL (nibble/bit in an NCD block, keyed by DID) and
-- VAG long-coding (byte.bit) + adaptation channels.
-- ----------------------------------------------------------------------------
create table if not exists coding_definition (
    id            uuid primary key default uuid_generate_v4(),
    ecu_id        uuid not null references ecu(id) on delete cascade,
    feature_key   text not null,                       -- 'mirror_fold_on_lock'
    label         text not null,                       -- 'Fold mirrors on lock'
    description   text,                                -- plain-English, embedded for RAG
    kind          text not null check (kind in ('fdl', 'long_coding', 'adaptation')),

    -- Where the value lives:
    did           int,                                 -- UDS Data Identifier (0x22/0x2E), FDL/long-coding block
    routine_id    int,                                 -- for adaptations done via RoutineControl (0x31)
    channel       int,                                 -- KWP/UDS adaptation channel (VAG)
    byte_offset   int,                                 -- position within the coding block
    bit_offset    int,                                 -- 0..7 (null => whole byte / nibble)
    bit_length    int not null default 1,

    -- Allowed values, plain-English -> raw:
    options       jsonb not null default '[]',         -- [{"label":"On","raw":1},{"label":"Off","raw":0}]

    security_level int,                                 -- UDS 0x27 level required (null => none)
    sfd_required  boolean not null default false,
    legal_class   text not null default 'comfort'      -- 'comfort' | 'lighting' | 'safety' | 'emissions'
                  check (legal_class in ('comfort','lighting','safety','emissions')),
    risk          text not null default 'low'          -- 'low' | 'medium' | 'high'
                  check (risk in ('low','medium','high')),
    source        text,                                 -- 'vcds_label', 'psdzdata', 'reverse_engineered', 'community'
    verified      boolean not null default false,       -- has this been tested on a real car?
    embedding     vector(1024),                         -- pgvector; description embedding (voyage-3: 1024 dims)
    created_at    timestamptz not null default now(),
    unique (ecu_id, feature_key)
);
create index if not exists coding_definition_embedding_idx
    on coding_definition using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- ----------------------------------------------------------------------------
-- DTC LIBRARY  — fault-code decode (Layer 1 + plain English)
-- ----------------------------------------------------------------------------
create table if not exists dtc_library (
    id            uuid primary key default uuid_generate_v4(),
    code          text not null,                       -- 'P2002'
    make          text,                                -- null => generic SAE J2012
    ecu_key       text,                                -- optional: which module reports it
    title         text not null,                       -- 'DPF efficiency below threshold'
    plain_english text,                                -- what it means for the driver (embedded for RAG)
    severity      text check (severity in ('info','low','medium','high','critical')),
    typical_cause text,
    typical_fix   text,
    est_cost_low  int,
    est_cost_high int,
    embedding     vector(1024),
    unique (code, make)
);
create index if not exists dtc_embedding_idx
    on dtc_library using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- ----------------------------------------------------------------------------
-- VEHICLES + SCAN HISTORY  — powers the fault-trend feature
-- ----------------------------------------------------------------------------
create table if not exists vehicle (
    id            uuid primary key default uuid_generate_v4(),
    user_id       uuid,                                -- Supabase auth user
    vin           text,
    plate         text,
    platform_id   uuid references platform(id),
    make          text, model text, year int,
    created_at    timestamptz not null default now()
);

create table if not exists scan (
    id            uuid primary key default uuid_generate_v4(),
    vehicle_id    uuid not null references vehicle(id) on delete cascade,
    scanned_at    timestamptz not null default now(),
    mileage       int,
    health_score  int,
    raw_codes     jsonb not null default '[]'          -- [{"ecu":"DDE","code":"P2002","status":"confirmed"}]
);

-- ----------------------------------------------------------------------------
-- CODING AUDIT  — SAFETY: every write recorded, every change reversible
-- ----------------------------------------------------------------------------
create table if not exists coding_audit (
    id             uuid primary key default uuid_generate_v4(),
    vehicle_id     uuid references vehicle(id),
    user_id        uuid,
    ecu_id         uuid references ecu(id),
    definition_id  uuid references coding_definition(id),
    vin            text,
    performed_at   timestamptz not null default now(),
    previous_value bytea,                              -- full coding block BEFORE (for revert)
    new_value      bytea,                              -- full coding block AFTER
    chosen_option  text,                               -- 'On'
    result         text not null default 'applied'     -- 'applied' | 'reverted' | 'failed'
                   check (result in ('applied','reverted','failed')),
    note           text
);

-- ----------------------------------------------------------------------------
-- ROW LEVEL SECURITY (tighten before production — users see only their data)
-- ----------------------------------------------------------------------------
alter table vehicle       enable row level security;
alter table scan          enable row level security;
alter table coding_audit  enable row level security;
-- Reference tables (platform/ecu/coding_definition/dtc_library) are read-mostly
-- and can be exposed read-only to authenticated users via policies you define.
