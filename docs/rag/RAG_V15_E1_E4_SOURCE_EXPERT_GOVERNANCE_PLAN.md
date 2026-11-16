# RAG V1.5 E1/E4: authoritative references and expert verification — follow-up plan

Status: **PLAN ONLY, 2026-11-16.** No code, registry entry, corpus document or approval is added by this plan.
It is kept apart from the E3 code change on purpose. It records what is verified, what is not, and what has to happen
before any scientific reference can support detection (E1) or an approval can rest on a qualified human (E4).

Nothing below is a verification. Every name of a person, role holder or approval is to be supplied by the project
owner; none is invented here.

## 1. Why it matters

E2/E7 detect conflicts only against the reference registry (`backend/knowledge/integrity/reference_registry*.json`),
and E3 contains only what was detected. With an unverified registry, a poisoned claim that no entry covers is
approved without a finding and cited without a warning (dev3-01, `test_rag_source_integrity_gap.py`; E3 replay
`test_12i` on the E3 branch). Conversely, an entry that is itself wrong can block a correct document.

## 2. Inventory (as of `integrate/rag-v15` 5f7e730)

| Reference / source | What exists | Verified against the primary document by a named human? | Missing |
|---|---|---|---|
| `ref-ch4-awd-not-eliminated` (qualitative, `verification.status: engine_config_pointer`) | pointer to `backend/config/emission_factors.yaml` (IPCC 2019 Refinement Vol. 4 Ch. 5 Table 5.12) | **No.** The YAML's `VERIFIED` is the project's own citation check; `methodology.domain_expert_review: PENDING` | artifact hash on the entry, page, human evidence file, rights |
| `ref-water-records-required` (qualitative, `project_policy`) | internal rule `data.completeness.water` | **No** — internal policy, not an external authority | an external MRV source (QĐ 4801 annex unavailable) |
| numeric registry `kn-reference-registry-2` | schema, loader, closed conversion table; **0 entries** | n/a | everything |
| IPCC 2019 Refinement Vol. 4 Ch. 5 (A1) and Ch. 11 (A2) | publisher URL, bytes, SHA-256 and PDF/printed pages recorded by a machine reading (`RAG_V15_M5_REFERENCE_REGISTRY_DESIGN.md` §2-3) | **No** (machine reading; spanning table cells ambiguous) | named human re-check per row; **rights not cleared** (`ipcc.ch/copyright` not read; owner decision required) |
| QĐ 2626/QĐ-BTNMT, Appendix III | no first-party artifact | No | a first-party copy (browser search of vbpl.vn / vanban.chinhphu.vn, or the ministry) |
| QĐ 4801/QĐ-BNNMT, MRV annex | decision cover page only | No | the annex from the issuer |
| QĐ 4043 (rice procedure) | Cà Mau provincial copy of the annex; signature chain verified | No | the complete original decision; expert reading of the straw-timing inconsistency (3 vs 2 weeks) |
| QĐ 1490 | complete portal-signed scan, no text layer | No | text layer / OCR policy (no OCR in V1.3) |
| C1-04 NAEC rice/coffee book | prefilter PASS, gate PARTIAL | No | rights; section-path extraction; SFp/N2O conflict with the registry |

Merely transcribed or secondary: everything above that is a pointer, a machine reading or a private legal-portal
copy. Private portals (thuvienphapluat.vn, luatvietnam.vn) and press articles are pointers only.

Missing version, page or effective date: both qualitative entries (no page on the entry); QĐ 2626/4801 (no artifact);
QĐ 4043 (decision page missing).

## 3. Source-ingestion checklist for an authoritative reference entry

Every step is recorded in the entry or in an evidence file whose hash the entry stores. A step that cannot be met
keeps the entry `unverified`. An unverified entry may raise a finding for a human to review; it must never become a
recommendation rule, an M05 rule input or proof of correctness.

1. **Artifact.** The file comes from the issuer's own HTTPS host. Record the URL, retrieval date, byte count and SHA-256.
2. **Authenticity.** For a Vietnamese decision: the signature chain is checked against the official Ban Cơ yếu
   anchor, with strict CRL, and the number and date are read from the signature widgets. Otherwise: the issuer page
   links the file.
3. **Completeness.** The decision page and every annex relied on are present. A cover page alone does not count.
4. **Identity.** Record the document number, issuer, version or edition, and the date it takes effect. When that date
   is null, record the reason.
5. **Exact location.** Record the PDF page, the printed page, and the table, equation or paragraph. For a table cell,
   record the row and column labels as printed. A cell spanning several rows needs a human reading.
6. **Verbatim passage.** Copy the passage, or the cell value with its unit as printed, from the artifact, never from a
   secondary source. Record the passage's own hash.
7. **Applicability.** Record the region, regime, baseline and the quantity the value is per. A conversion uses only
   the closed table (`reference_numeric.py`).
8. **Rights.** `rights.status` is cleared for this exact use: storing a value, quoting a passage, or adding the
   document to the retrieval corpus. `not_cleared` is refused by the loader.
9. **Human verification (E4).** A named, qualified person re-reads the passage in the artifact. Their evidence file
   is hashed into `verification.human.evidence_sha256`. An AI reading, or an AI review, is never this step.
10. **Internal consistency.** Check the source against itself. A contradiction keeps the entry unverified until an
    expert resolves it, and the resolution is recorded.
11. **Versioning.** Bump `registry_version`. A changed entry is a new entry, and the old one is kept for re-reviews.

## 4. Expert verification (E4)

- Every expert reviewer, approver, archivist and re-verifier in tests is a synthetic fixture. No qualified human has
  reviewed the real corpus or the registry.
- Real verification must be performed by qualified, **named** humans whose identity, qualification category and
  appointment are recorded by the owner (M2 `knowledge_expert_reviews` carries the fields; the people do not exist yet).
- No fictional expert identity, approval or verification may be created to satisfy a gate, a test outside a
  rolled-back fixture, or a document.
- Option C of E3 (re-admission after independent verification) depends on this: it needs a second, distinct, real
  verified reviewer and a database-enforced concurrence record.

## 5. IPCC and other protected material

- No IPCC table, value, passage or PDF is added to the repository, the registry or the retrieval corpus until the
  owner has decided on the permitted use (read `https://www.ipcc.ch/copyright/` in a browser, or ask the IPCC
  Secretariat). The engine's existing configuration pointers are unchanged by this plan.
- The same applies to any third-party book or guide whose rights are ambiguous (for example C1-04).

## 6. Proposed order (each step needs owner approval)

1. Owner decision on IPCC rights, and on which uses of each document are required.
2. Owner names the qualified reviewers (E4) and their qualification evidence.
3. Obtain first-party copies of QĐ 2626 Appendix III and the QĐ 4801 annex, plus the complete QĐ 4043 decision.
4. Per entry: complete checklist steps 1-11, then the named human verification. Only then mark the entry `verified`.
5. Re-run the dev3-01 replay with the verified entries and record whether detection changes. This is not a closure
   of dev3-01 by itself.
6. Design Option C only after steps 2 and 4.

## 7. Decisions required from the owner

- the permitted use of IPCC material (store values? quote passages? corpus?);
- who the qualified reviewers are, and what qualifies them;
- whether internal project policy (`ref-water-records-required`) may stay a registry entry, or must wait for an
  external MRV source;
- the OCR policy for scan-only official decisions (QĐ 1490).
