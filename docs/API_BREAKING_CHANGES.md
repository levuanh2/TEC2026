# API breaking changes (acknowledged)

`scripts/ci/openapi_check.py --base-ref origin/main` compares the contract the
backend generates with the base branch's `docs/openapi.json`. A breaking change
(removed operation, new required parameter/field, removed or retyped response
field, changed auth requirement) fails CI unless an exact `ACK <id>` line below
acknowledges it. Add ACK lines in the same PR as the change, with the reason;
reviewers approve them like code.

## 2026-09-27 — contract reconciliation (CI hardening v2)

`docs/openapi.json` had not been regenerated since before the season lifecycle,
provisioning and MRV export work: the code on `main` served 55 operations, the
document listed 44. Regenerating it surfaced five differences that were
**already live on main** (no code change in this PR):

- MRV export responses no longer expose storage location: removed deliberately
  with `20260915100000_restrict_mrv_exports_storage_client_access` (clients
  download through FastAPI, never directly from Storage).
- `factor_set_id` on an MRV export and `created_by` on activity write responses
  are nullable: seeded/legacy activities have no recorded author, and an export
  can exist before a factor set is attached.

ACK removed-response-field:GET /v1/mrv/exports/{mrv_export_id}:storage_bucket
ACK removed-response-field:GET /v1/mrv/exports/{mrv_export_id}:storage_object_path
ACK response-type-changed:GET /v1/mrv/exports/{mrv_export_id}:factor_set_id
ACK response-type-changed:PATCH /v1/activities/{activity_id}:created_by
ACK response-type-changed:POST /v1/crop-seasons/{crop_season_id}/activities:created_by
