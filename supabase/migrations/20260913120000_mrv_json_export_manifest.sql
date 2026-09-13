-- Let an MRV case produce a JSON evidence package.
--
-- Two things in the existing `mrv_exports` contract block it today, both found
-- against the real database rather than the docs:
--
--   1. `public.export_format` is ('pdf','xlsx'). The JSON manifest is the source
--      contract those two will later be rendered from, so it needs its own
--      value rather than being smuggled in as one of them.
--
--   2. `mrv_exports.factor_set_id` is NOT NULL. A factor set only exists once a
--      carbon calculation has been run against an imported set, and on a
--      database where the factors have not been imported there is no set at all
--      (hosted dev today: 0 rows in `emission_factor_sets`). That made an export
--      impossible precisely in the state the package most needs to describe —
--      "carbon is unavailable, here is everything else plus a warning". The
--      column stays a real foreign key and is still populated whenever a carbon
--      calculation backs the package; it is now nullable so that the absence of
--      carbon is recorded honestly instead of blocking the export.
--
-- Nothing else about the table changes. In particular `mrv_export_warning_chk`
-- is left exactly as it is: a package that is not finalized MUST carry
-- `warning_text`, which is the behaviour this feature wants, not one to relax.

alter type public.export_format add value if not exists 'json';

alter table public.mrv_exports
  alter column factor_set_id drop not null;

comment on column public.mrv_exports.factor_set_id is
  'Emission factor set backing this package. NULL when the package was generated '
  'with no carbon calculation available; the manifest then records '
  'carbon.status = unavailable together with a warning.';

comment on column public.mrv_exports.export_payload is
  'The generated manifest, stored verbatim. This is the audit artifact: a '
  'download re-serves this snapshot and never rebuilds it from live data.';

comment on column public.mrv_exports.storage_object_path is
  'Canonical <organization_uuid>/<mrv_case_uuid>/<filename> path for this export. '
  'For JSON packages the bytes live in export_payload, and no object is written '
  'to the bucket; the path fixes the download filename and keeps one export per '
  'name. Binary evidence packaging is a later part of M07.';

-- Listing a case's exports newest-first is the only access pattern so far.
create index if not exists mrv_exports_case_generated_idx
  on public.mrv_exports (mrv_case_id, generated_at desc);
