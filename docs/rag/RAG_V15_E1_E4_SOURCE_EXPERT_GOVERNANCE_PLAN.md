# RAG V1.5 E1/E4: scientific evidence and expert governance (plan and index)

Status: **DOCUMENTATION ONLY, 2026-11-16. E1 OPEN, E4 OPEN, dev3-01 OPEN.**

This PR adds no code, registry entry, corpus document, approval, identity or migration. Nothing in it verifies a
source or qualifies a person. It is kept apart from the E3 code change (Draft PR #81, stacked on #78) and does not
depend on it.

## 1. Why it matters

E2 and E7 detect conflicts only against the reference registry, and E3 (#81) contains only what was detected. Two
consequences:

- **Unverified registry, missed poison.** With an unverified registry, a poisoned claim that no entry covers is
  approved without a finding and cited without a warning. This is dev3-01, `test_rag_source_integrity_gap.py`, and
  `test_12i` on #81.
- **Wrong entry, blocked document.** An entry that is itself wrong can block a correct document.

## 2. Documents

| Document | Contents |
|---|---|
| `RAG_V15_E1_SOURCE_REGISTRY_AUDIT.md` | tool check vs human verification; classification of every source; the reference metadata record; per-source records; the internal operational source policy; status of the Vietnamese decisions |
| `RAG_V15_E1_RIGHTS_AND_OCR.md` | IPCC licensing findings and the exposure already in the repository; the rights-clearance checklist; the OCR policy and its auditable review record |
| `RAG_V15_E4_EXPERT_GOVERNANCE.md` | qualification criteria; separation of duties; the E3 Option C database record design and its prerequisites; E4 closure criteria |

## 3. Proposals for READ-tier contested citations (Phase 8, NOT implemented here)

The owner's requirement (2026-11-16):

- keep the title for an authorized caller;
- show beside it, verbatim: "Tài liệu đang có nội dung khoa học cần xác minh lại; không sử dụng làm căn cứ hướng dẫn
  canh tác.";
- no tooltip;
- no implied endorsement;
- no cross-tenant metadata;
- no unsafe navigation links;
- never action advice;
- tests for visibility, authorization and accessibility.

Gap analysis against #81 head `6d85b55`:

| Requirement | #81 today | Gap | Proposed change (separate code PR, stacked on #81) |
|---|---|---|---|
| exact warning text | `Cảnh báo: tài liệu này có mâu thuẫn khoa học (<labels>) và cần được xác minh lại; không dùng làm hướng dẫn canh tác.` | wording differs | set `CITATION_CONFLICT_WARNING` to the owner's sentence (labels, if kept, as a second sentence); update the DB, offline, route and web tests |
| beside the title, not a tooltip | a visible `role="note"` paragraph, but after section, type, date and the link | not beside the title | render it directly after `.aiq__cite-title`, with `aria-describedby` linking title and warning; DOM test for order and accessible name |
| title must not imply endorsement | the composed answer says "Các đoạn tài liệu đã duyệt…", and the panel hint says "tài liệu đã duyệt" | "đã duyệt" (approved) reads as endorsement of a contested source | when a cited source is contested: neutral wording ("tài liệu trong kho"), and no "đã duyệt" next to that citation; test |
| no unsafe or trusted navigation | `Mở nguồn` link rendered for any `https` URL, contested or not | a contested source is still offered as a trusted link | for a contested citation, render no link, or a plain-text URL marked "cần xác minh lại"; test |
| no cross-tenant titles or metadata | E5 recheck + C1 citation check; #81 `test_12f` (other HTX: not retrieved, `citation_mismatch`, helpers return nothing) | none found | keep; add a route-level test with a foreign contested chunk |
| never action advice | READ intents never reach a model; the trusted composer has no recommendation slot; #81 disguised-action tests | none found | keep |
| accessibility | `role="note"`, not colour-only | needs an explicit test | axe/role test in the Vitest DOM suite; contrast check of the `--warning-*` tokens |

## 4. Proposed order of work (each step needs owner approval)

1. Rights: a person reads `ipcc.ch/copyright` in a browser and fills the clearance checklist per intended use. The owner
   decides on the existing IPCC-derived content in the repository (rights doc §2.4).
2. The owner appoints qualified reviewers (E4 §2), with evidence.
3. Obtain first-party copies of:
   - QĐ 2626 with its appendices;
   - the QĐ 4801 annex;
   - the complete QĐ 4043 decision.
4. Per reference: complete the metadata record (audit §3), then the human verification. Only then is it
   `human_verified`.
5. The owner adopts the OCR policy before QĐ 1490 is used.
6. The READ-tier citation changes (§3) are a separate code PR on #81.
7. Option C design review only after steps 2 and 4.
8. Re-run the dev3-01 replay with the verified entries. A changed detection result does not close dev3-01 by itself.

## 5. Owner actions

- Read and record the IPCC copyright terms (no automated access is possible). Decide each intended use and the
  existing repository content.
- Name and appoint the qualified reviewers. Define the qualification thresholds and conflicts of interest.
- Obtain the Vietnamese decisions from their issuers (browser search of `vbpl.vn` / `vanban.chinhphu.vn` /
  `mae.gov.vn`, or a written request).
- Adopt, or amend, the OCR policy.
- Decide whether internal rules (`ref-water-records-required`) may stay as `detection_only` entries.
- Approve the READ-tier citation change proposal (§3) as a separate code PR.
- Approve the Option C policy when its prerequisites exist.
