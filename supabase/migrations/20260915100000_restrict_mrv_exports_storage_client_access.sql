-- M7 (docs audit): no direct client access to the `mrv-exports` Storage bucket.
--
-- WHAT WAS WRONG
--   The baseline created one set of `storage.objects` policies for BOTH MRV
--   buckets ('mrv-evidence', 'mrv-exports'):
--     * SELECT: private.user_can_read_organization(<first path folder>) — any
--       active organization member (farmer included) and any
--       enterprise_viewer/regulator of a grantee organization;
--     * INSERT/UPDATE/DELETE: private.user_is_org_manager(<first path folder>).
--   `20260913150000_mrv_xlsx_export_artifacts` turned `mrv-exports` objects into
--   real artifacts at `<organization_id>/<mrv_case_id>/<file>` and restricted the
--   `mrv_exports` metadata rows to `private.user_can_manage_mrv_case`, but left
--   the Storage policies above untouched. A farmer or grant reader holding a
--   valid JWT could therefore list and download export artifacts straight from
--   the Storage API, bypassing the management-only rule that
--   `GET /v1/mrv/exports/{id}/download` enforces. A manager could also replace or
--   delete an artifact from a client, outside the backend's integrity checks.
--
-- WHAT THIS DOES
--   * The four `mrv_files_storage_*` policies are replaced by the same four
--     policies scoped to 'mrv-evidence' only. Behaviour for `mrv-evidence` is
--     unchanged (it has no upload flow yet and its access rule is a separate
--     product decision).
--   * No policy for role `authenticated` (or `anon`) mentions 'mrv-exports' any
--     more. RLS is enabled on `storage.objects`, so every client operation on
--     that bucket — list, download, upload, overwrite, delete — is denied.
--   * The backend reads and writes `mrv-exports` with the service role, which
--     bypasses RLS, and serves artifacts only through FastAPI after
--     authorization and SHA-256 verification. That path is unaffected.
--   * `plant-images` policies and the buckets themselves (still private) are not
--     touched. No signed or public URL is created anywhere.

drop policy if exists mrv_files_storage_select on storage.objects;
drop policy if exists mrv_files_storage_insert on storage.objects;
drop policy if exists mrv_files_storage_update on storage.objects;
drop policy if exists mrv_files_storage_delete on storage.objects;

drop policy if exists mrv_evidence_storage_select on storage.objects;
create policy mrv_evidence_storage_select on storage.objects for select to authenticated
using (
  bucket_id = 'mrv-evidence'
  and private.user_can_read_organization(private.try_uuid((storage.foldername(name))[1]))
);

drop policy if exists mrv_evidence_storage_insert on storage.objects;
create policy mrv_evidence_storage_insert on storage.objects for insert to authenticated
with check (
  bucket_id = 'mrv-evidence'
  and private.user_is_org_manager(private.try_uuid((storage.foldername(name))[1]))
);

drop policy if exists mrv_evidence_storage_update on storage.objects;
create policy mrv_evidence_storage_update on storage.objects for update to authenticated
using (
  bucket_id = 'mrv-evidence'
  and private.user_is_org_manager(private.try_uuid((storage.foldername(name))[1]))
)
with check (
  bucket_id = 'mrv-evidence'
  and private.user_is_org_manager(private.try_uuid((storage.foldername(name))[1]))
);

drop policy if exists mrv_evidence_storage_delete on storage.objects;
create policy mrv_evidence_storage_delete on storage.objects for delete to authenticated
using (
  bucket_id = 'mrv-evidence'
  and private.user_is_org_manager(private.try_uuid((storage.foldername(name))[1]))
);
