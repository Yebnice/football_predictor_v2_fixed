-- PjDigitalServices v1.2.2 support complaint transaction-detail migration

alter table feedback add column if not exists service_type text;
alter table feedback add column if not exists transaction_id text;
alter table feedback add column if not exists transaction_amount numeric;
alter table feedback add column if not exists requested_data text;
alter table feedback add column if not exists beneficiary text;
alter table feedback add column if not exists transaction_at timestamptz;
alter table feedback add column if not exists transaction_details text;

create index if not exists feedback_transaction_id_idx on feedback (transaction_id);
