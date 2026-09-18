-- PjDigitalServices production schema.
-- Run this on a fresh Supabase project. For an existing project, run the
-- ALTER statements in the migration block at the bottom first.
create extension if not exists pgcrypto;

create table if not exists orders (
  reference             text primary key,
  order_type            text not null,
  network               text,
  phone                 text not null,
  email                 text not null,
  amount                numeric not null,
  bundle_id             text,
  afa_details           jsonb,
  meter_number          text,
  tv_details            jsonb,
  checker_details       jsonb,
  tier_details          jsonb,
  status                text not null default 'pending',
  fulfilled             boolean not null default false,
  fulfillment_status    text not null default 'pending',
  fulfillment_attempts  integer not null default 0,
  processing_started_at   timestamptz,
  last_fulfillment_error text,
  payment_verified_at   timestamptz,
  payment_amount       numeric,
  result                jsonb,
  fail_reason           text,
  created_at            timestamptz not null default now(),
  fulfilled_at          timestamptz,
  manual_review_notified_at timestamptz,
  customer_delay_notified_at timestamptz,
  manual_review_at        timestamptz,
  manual_review_resolution text,
  manual_review_resolved_at timestamptz,
  urgent_review_notified_at timestamptz
);

create table if not exists customers (
  id uuid primary key default gen_random_uuid(),
  name text,
  email text,
  phone text,
  created_at timestamptz not null default now()
);

create table if not exists feedback (
  id uuid primary key default gen_random_uuid(),
  case_reference text unique not null,
  name text not null,
  email text,
  phone text,
  order_reference text,
  category text not null default 'general',
  message text not null,
  service_type text,
  transaction_id text,
  transaction_amount numeric,
  requested_data text,
  beneficiary text,
  transaction_at timestamptz,
  transaction_details text,
  status text not null default 'open',
  created_at timestamptz not null default now()
);

create index if not exists orders_email_idx on orders (lower(email));
create index if not exists orders_phone_idx on orders (phone);
create index if not exists orders_fulfillment_idx on orders (fulfilled, fulfillment_status, created_at);
create index if not exists orders_created_at_idx on orders (created_at desc);
create index if not exists feedback_created_at_idx on feedback (created_at desc);

alter table orders enable row level security;
alter table customers enable row level security;
alter table feedback enable row level security;

-- Production security model: the application uses server-side Supabase secret
-- access only. No public table policies are intentionally granted here.

-- Existing-project migration (safe/idempotent):
-- alter table feedback add column if not exists case_reference text;
alter table feedback add column if not exists service_type text;
alter table feedback add column if not exists transaction_id text;
alter table feedback add column if not exists transaction_amount numeric;
alter table feedback add column if not exists requested_data text;
alter table feedback add column if not exists beneficiary text;
alter table feedback add column if not exists transaction_at timestamptz;
alter table feedback add column if not exists transaction_details text;
-- Existing rows should be backfilled with unique SUP-YYYYMMDD-XXXXX references before adding a NOT NULL/UNIQUE constraint.
-- alter table orders add column if not exists fulfillment_status text not null default 'pending';
-- alter table orders add column if not exists fulfillment_attempts integer not null default 0;
-- alter table orders add column if not exists processing_started_at timestamptz;
-- alter table orders add column if not exists manual_review_notified_at timestamptz;
-- alter table orders add column if not exists customer_delay_notified_at timestamptz;
-- alter table orders add column if not exists last_fulfillment_error text;
-- alter table orders add column if not exists payment_verified_at timestamptz;
-- alter table orders add column if not exists payment_amount numeric;
-- alter table orders add column if not exists manual_review_at timestamptz;
-- alter table orders add column if not exists manual_review_resolution text;
-- alter table orders add column if not exists manual_review_resolved_at timestamptz;
-- alter table orders add column if not exists urgent_review_notified_at timestamptz;
-- (Existing projects: these are already applied by migration_v1_2.sql / migration_v1_2_2.sql — this block is reference documentation, not meant to be re-run.)
-- update orders set fulfillment_status = case when fulfilled then 'fulfilled' else 'pending' end where fulfillment_status is null;
-- create index if not exists orders_fulfillment_idx on orders (fulfilled, fulfillment_status, created_at);
