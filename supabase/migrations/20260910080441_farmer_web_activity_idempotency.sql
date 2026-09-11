-- Farmer Web online submissions do not have a registered Flutter device.
-- Keep the existing (device_id, client_event_id) contract untouched and add a
-- separate, nullable idempotency key resolved from the authenticated actor.
alter table public.activities
  add column if not exists web_idempotency_key uuid;

create unique index if not exists activities_web_idempotency_uidx
  on public.activities (recorded_by, web_idempotency_key)
  where recorded_by is not null and web_idempotency_key is not null;
