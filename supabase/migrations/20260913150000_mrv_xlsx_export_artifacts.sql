-- M07 part 2: XLSX artifacts rendered from a canonical JSON snapshot.
--
-- 1. LINEAGE
--    An XLSX export is a *rendering* of one canonical manifest, never an
--    independent assembly of business data. `source_snapshot_export_id` records
--    which JSON snapshot it came from, so the lineage is a fact in the database
--    rather than a convention in the code.
--
--    The row also keeps its own copy of `export_payload`. That is deliberate
--    duplication: an audit row must stay self-describing even if the parent
--    snapshot is later removed, and `payload_sha256` lets anyone prove the two
--    rows rendered from byte-identical manifests.
--
-- 2. TWO CHECKSUMS, TWO MEANINGS
--    `file_sha256`    digest of the DOWNLOADABLE ARTIFACT bytes: the canonical
--                     manifest text for JSON, the workbook for XLSX.
--                     NOTE: part 1 wrote the MANIFEST digest into this column
--                     for JSON rows. Those two are not the same number -- the
--                     manifest digest deliberately excludes its own
--                     `package_integrity` block, while the served bytes include
--                     it. The backfill below therefore moves that value to
--                     `payload_sha256`, where it belongs, and the JSON download
--                     path verifies against the snapshot's own self-describing
--                     digest, so pre-part-2 rows keep verifying correctly.
--    `payload_sha256` digest of the CANONICAL MANIFEST, always, whatever the
--                     format. Two exports of the same snapshot in different
--                     formats share this value and differ in `file_sha256`,
--                     which is precisely how "same data, different file" is
--                     told apart from "different data".
--    Conflating them would make it impossible to tell "the spreadsheet was
--    altered" from "the underlying snapshot differs", which is exactly the
--    question an audit asks.
--
-- 3. METADATA IS NOW MANAGEMENT-ONLY
--    Until now `mrv_exports_select` allowed any organization member to read
--    export metadata. That was tolerable while `storage_object_path` pointed at
--    nothing: the payload was never selected and the path was an inert string.
--    This migration makes the path point at a REAL private object, so the same
--    row now describes a retrievable artifact. Export generation and download
--    are already restricted to `cooperative_manager`; metadata visibility is
--    brought in line with them rather than left as the one surface that is not.
--    `private.user_can_manage_mrv_case` is the existing helper for exactly this.

alter table public.mrv_exports
  add column if not exists source_snapshot_export_id uuid
    references public.mrv_exports(id) on delete set null,
  add column if not exists payload_sha256 text;

do $$ begin
  alter table public.mrv_exports
    add constraint mrv_export_payload_sha_chk
    check (payload_sha256 is null or payload_sha256 ~ '^[0-9a-fA-F]{64}$');
exception when duplicate_object then null; end $$;

-- An XLSX row must name the snapshot it rendered. A JSON row is the snapshot,
-- so it has no parent; allowing one would invite a snapshot-of-a-snapshot.
do $$ begin
  alter table public.mrv_exports
    add constraint mrv_export_snapshot_lineage_chk
    check (
      (format = 'json'::public.export_format and source_snapshot_export_id is null)
      or (format <> 'json'::public.export_format and source_snapshot_export_id is not null)
    );
exception when duplicate_object then null; end $$;

-- Part 1 put the manifest digest in `file_sha256`; move it to the column that
-- actually means that. `file_sha256` on those legacy rows is left as-is rather
-- than recomputed: reproducing the canonical serialization in SQL would be a
-- second implementation of the very thing the digest exists to pin down.
update public.mrv_exports
   set payload_sha256 = file_sha256
 where payload_sha256 is null
   and file_sha256 is not null
   and format = 'json'::public.export_format;

create index if not exists mrv_exports_source_snapshot_idx
  on public.mrv_exports (source_snapshot_export_id)
  where source_snapshot_export_id is not null;

comment on column public.mrv_exports.source_snapshot_export_id is
  'The canonical JSON snapshot this artifact was rendered from. NULL only for '
  'the JSON snapshot rows themselves. A renderer must never assemble business '
  'data of its own; this column is how that is auditable.';

comment on column public.mrv_exports.payload_sha256 is
  'SHA-256 of the canonical manifest (package_integrity.manifest_sha256), for '
  'every format. Distinct from file_sha256, which digests the downloadable '
  'artifact bytes; exports of one snapshot in different formats share this '
  'value and differ in file_sha256.';

comment on column public.mrv_exports.file_sha256 is
  'SHA-256 of the downloadable artifact bytes: the canonical manifest for JSON, '
  'the workbook for XLSX. Checked on download; a mismatch fails closed rather '
  'than serving an artifact that does not match its record.';

-- Metadata follows the artifact: manager-only, matching generate and download.
drop policy if exists mrv_exports_select on public.mrv_exports;
create policy mrv_exports_select on public.mrv_exports for select to authenticated
  using (private.user_can_manage_mrv_case(mrv_case_id));

drop policy if exists mrv_export_calcs_select on public.mrv_export_calculations;
create policy mrv_export_calcs_select on public.mrv_export_calculations for select to authenticated
  using (exists (
    select 1 from public.mrv_exports e
    where e.id = mrv_export_id and private.user_can_manage_mrv_case(e.mrv_case_id)
  ));
