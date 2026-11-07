# HTX (cooperative) assistant — organization-scoped Q&A (RESEARCH PROPOSAL)

Branch: `research/rag-d8-strategy-c`. Date: 2026-11-07. Not part of #27–#32.

## Is it required?

Yes for managers. The V1 endpoint `POST /v1/crop-seasons/{id}/questions` answers about **one
season** the caller can read. A cooperative manager's real questions are organization-level:
"Hộ nào chưa ghi lượng nước?", "Bao nhiêu vụ chưa tính được phát thải?", "Thửa nào phát thải trên kg
cao nhất?", "HTX còn thiếu gì cho MRV?". Today they would have to open every season. Widening the
season endpoint (accepting an org id, iterating seasons) would silently change its access contract
and is **not** proposed.

## Proposal

- New, separate route: `POST /v1/organizations/{organization_id}/questions`, its own feature switch,
  its own route-auth manifest entry and positive-auth tests.
- Authorization: caller JWT → `private.user_is_org_member(organization_id)` with an
  **organization role** (`cooperative_manager`, later `enterprise_viewer` read-only); never a farm role
  inference; a non-member gets 404 like every other scope miss. Former members lose access in the next
  statement (existing RLS semantics).
- Facts only from **existing authoritative aggregate APIs** — the same services behind
  `/v1/organizations/{id}/summary`, farm performance, Carbon `status_many` and readiness — never a
  new aggregation in the RAG layer (same "pick, don't compute" rule as `build_season_context`).
  Farm/season rows enter as facts with their own `crop_season_id`/`organization_id` so
  `assert_fact_scope` still proves every fact belongs to the caller's organization.
- Intents: READ only (`org_summary`, `org_data_gaps`, `org_mrv_gaps`, `org_compare`); no action
  intents (managers have no Core V1 WRITE on farms). Answers composed by templates (strategy B);
  strategy C only after its own evaluation.
- Knowledge: public + the organization's tenant documents (farm-scoped documents excluded unless the
  manager can read that farm) — the RPC needs an org-scoped variant (**new migration + approval**).
- Privacy: an org answer aggregates many households: no names/phones in facts; counts and codes only.

## Tests required before any implementation PR

Cross-tenant (another HTX's manager → 404, no facts), former manager, farm viewer of one farm
(must not get org answers), enterprise viewer (read-only, no action), aggregate parity with the
existing summary endpoint (same numbers), no stale answer after organization switch in the UI.
