-- PjDigitalServices v1.2.0 migration for existing Supabase projects.
-- Run after the previous production schema.

alter table orders add column if not exists manual_review_notified_at timestamptz;
alter table orders add column if not exists customer_delay_notified_at timestamptz;

alter table feedback add column if not exists case_reference text;

-- Generate support-case references for legacy feedback rows that do not have one.
update feedback
set case_reference = 'SUP-' || to_char(created_at, 'YYYYMMDD') || '-' || upper(substr(replace(id::text, '-', ''), 1, 5))
where case_reference is null;

create unique index if not exists feedback_case_reference_idx on feedback(case_reference);

-- New rows should always receive a case reference from the application.


alter table orders add column if not exists manual_review_resolution text;
alter table orders add column if not exists manual_review_resolved_at timestamptz;

alter table orders add column if not exists manual_review_at timestamptz;
alter table orders add column if not exists urgent_review_notified_at timestamptz;

