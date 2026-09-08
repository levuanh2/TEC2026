# Web Dashboard → Backend Gaps

The dashboard must keep all domain reads behind FastAPI. The endpoints below do not exist in `backend/api.py` as of 2026-09-08; the web UI uses explicitly labelled development mock data instead.

| Missing endpoint | Why needed | Expected request | Expected response | Priority | Backend owner |
|---|---|---|---|---|---|
| `GET /v1/me` | Confirm frontend role/profile after JWT validation | Bearer JWT | profile id, display name, role, organizations | P0 | Backend/Auth |
| `GET /v1/farms` | Manager farm list and cooperative comparison | filters/pagination | farm code/name/location/plot count/area plus nullable aggregate metrics | P0 | Backend |
| `GET /v1/farms/{id}` | Farm detail | Bearer JWT | farm information, authorized plots and seasons | P0 | Backend |
| `GET /v1/plots/{id}` | Plot detail | Bearer JWT | plot metadata and crop seasons | P0 | Backend |
| `GET /v1/crop-seasons/{id}` | Season metadata and yield | Bearer JWT | crop-season attributes; nullable yield | P0 | Backend |
| `GET /v1/crop-seasons/{id}/activities` | Activity table/audit chronology | Bearer JWT, pagination | occurred_at, activity type/detail, recorded_by, source | P0 | Backend |
| `GET /v1/crop-seasons/{id}/metrics` | Water/fertilizer/cost per kg | Bearer JWT | nullable backend-derived metrics plus warnings/provenance | P1 | Backend |
| `GET /v1/reports/mrv` | Read-only MRV reporting | Bearer JWT | six-step status and evidence metadata | P1 | Backend |

Do not expose the Supabase service-role key to close any of these gaps. Responses must enforce the same RLS-derived scope as the existing Carbon endpoints.
