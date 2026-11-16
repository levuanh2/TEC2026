# RAG V1.5 E1: rights clearance (IPCC and third-party material) and OCR review policy

Status: **POLICY AND CHECKLISTS, 2026-11-16.** No material is added to the repository or the retrieval corpus. Nothing
here is legal advice. A rights decision belongs to the owner, and to counsel where needed.

Index: `RAG_V15_E1_E4_SOURCE_EXPERT_GOVERNANCE_PLAN.md`.

## 1. Owner policy (2026-11-16)

- No redistribution of full IPCC documents through the repository.
- No automatic ingestion of uncleared IPCC text into the retrieval corpus.
- Metadata and official source links are permitted.
- Any use beyond permitted exceptions needs separate legal permission or a clearly applicable licence.
- An official publication is not presumed to be in the public domain.
- Every use records its exact intended purpose: local research, internal validation, retrieval corpus, public-facing
  output, or commercial deployment.
- Protected tables or figures are not copied into committed fixtures without permission.

## 2. IPCC licensing: what was actually established

### 2.1 Primary policy page: NOT READ

`https://www.ipcc.ch/copyright/` answered HTTP 403 to automated access on 2026-11-12 and again on 2026-11-16.
`https://archive.ipcc.ch/home_copyright.shtml` also answered 403. **The official terms have not been read by this
project.** A person must open the page in a browser and record its text, with the date, in the clearance record (§2.5).

### 2.2 Read, first-party

`https://www.ipcc-nggip.iges.or.jp/public/2019rf/index.html` (the 2019 Refinement landing page, read 2026-11-16):

- footer "© 2026 Intergovernmental Panel on Climate Change (IPCC)";
- the "Copyright" link points to `https://www.ipcc.ch/copyright/` (not readable, §2.1);
- the page itself states no licence;
- a full download (`pdf/2019rf_all_in.zip`) is offered without stated terms.

**Download availability is not a licence.**

### 2.3 Secondary only (search-result summaries, 2026-11-16). NOT a basis for any decision

Search summaries attribute the following to the IPCC page:

- reproduction of a limited number of figures or short excerpts for personal, non-commercial use, without formal
  permission, if the source is fully credited;
- otherwise, written permission from the IPCC Secretariat (`copyright@ipcc.ch`, on letterhead), granted only for use
  of the material exactly as published;
- commercial use and derivative products are prohibited without permission;
- an older archived page reportedly forbade redistributing, compiling or creating derivative works.

Search results also list Cambridge University Press copyright notices for some IPCC reports under CC BY-NC-ND 4.0,
with third-party content excluded. The one notice fetched could not be read, and the 2019 Refinement is a TFI
publication, not one of those editions. **No CC licence is assumed for the 2019 Refinement.** The 2026-10-07
inventory recorded the same reading: storage, retrieval and compilation are not permitted without written permission.

### 2.4 Exposure already in the repository (owner decision required)

These committed files reproduce IPCC-derived content. **This audit does not change them**, because the decision on
them belongs to the owner:

| File | Content | Note |
|---|---|---|
| `docs/rag/RAG_V15_M5_REFERENCE_REGISTRY_DESIGN.md` §3 | machine-read rows of Tables 5.11, 5.11A, 5.12, 5.13, 5.14 and 11.1, including caption text and values | table transcription, beyond metadata and links |
| `backend/config/emission_factors.yaml` | IPCC Tier 1 default values with table citations | engine configuration; individual factual values, but a systematic compilation |
| `backend/tests/fixtures/factor_sets/*.yaml` | variants of the same factor set | test fixtures |

Options for the owner, with the owner choosing:

- (a) record a rights basis for each use (permission, licence, or a counsel-confirmed exception);
- (b) replace the transcribed tables in the M5 design with locators and hashes only;
- (c) accept as-is for local research, and record that the content must not ship in public or commercial outputs.

### 2.5 Rights-clearance checklist (per source, per intended use)

1. The official policy text was read by a person: URL, date, and a saved copy outside Git with its SHA-256.
2. Rights holder identified (IPCC; publisher; third parties inside the work: figures, tables, maps).
3. Exact intended use: local research / internal validation / retrieval corpus / public-facing output / commercial
   deployment. Each needs its own answer.
4. Scope of the material: metadata only / short credited excerpt / single values / whole tables or figures / full text.
5. Is the use within the stated exception? Answer yes or no, with the sentence it relies on. If unclear, the answer is no.
6. When permission is needed: request sent (to whom, when), the exact material listed, the response stored (hash).
7. Attribution text as required: report name, publisher, page and figure or table numbers.
8. Modification: whether figures or captions may be changed (assume not).
9. Downstream: where the material may appear (repo, corpus, API answer, UI, exports), and where it must not.
10. Review date, and the person responsible for re-checking.

Until items 1-6 are complete for a use, that use is not cleared. The loader already refuses `rights.status:
not_cleared` for numeric entries.

## 3. OCR policy (extraction assistant, never authority)

OCR may help a human read a scan. Its output is never evidence by itself.

1. **Original.** Keep an authorized, immutable copy of the original outside Git where appropriate (for example the
   private `knowledge-artifacts` bucket), with its SHA-256, byte count, source URL, acquisition date and
   publication metadata (issuer, number, date, signer as printed).
2. **Processing record.** OCR software and version, language model or data, settings, page range and date. Store the
   OCR output's own hash.
3. **Separation.** OCR-derived text is stored and labelled as `ocr_derived`, apart from evidence about the original.
   Citations point at the original page, never at OCR text.
4. **Human comparison.** A named person compares each used passage with the page image, page by page.
5. **Double check.** Every numeric value, decimal separator, range, unit, sign, table heading, column/row label,
   footnote marker and effective date is checked twice. The second check is by a different person where a value
   becomes a trusted reference.
6. **Unclear means UNRESOLVED.** An illegible or inconsistent reading is recorded as `UNRESOLVED`, with the page and
   region. It is never guessed or "normalized".
7. **No auto-approval.** OCR text is never marked approved evidence by a tool. The pipeline keeps refusing
   `no_text_layer` sources until this review exists.
8. **Conflicts stay visible.** A value that differs between pages, editions or the OCR and the image is recorded as a
   conflict, never silently reconciled.
9. **Trusted reference** needs a qualified, named verifier (E4) after steps 1-8.
10. **Scope.** No bulk OCR over copyrighted corpora. OCR is run only on documents whose rights for the intended use
    are cleared (§2.5), and only on the pages needed.

### 3.1 OCR review record (auditable fields)

```yaml
ocr_review_id: <id>
original: {url: <...>, sha256: <...>, bytes: <...>, acquired_on: <...>, storage_ref: <outside Git>}
publication: {issuer: <...>, number: <as printed>, date: <as printed>, signer: <as printed>}
processing: {software: <name>, version: <...>, language_data: <...>, settings: <...>, run_on: <...>, output_sha256: <...>}
pages: [{pdf_page: <n>, printed_page: <...>, image_sha256: <...>}]
passages:
  - page: <n>
    region: <bbox or description>
    ocr_text_sha256: <...>
    human_reading_matches: yes | no | UNRESOLVED
    numeric_checks: [{value_as_seen: <...>, unit: <...>, check_1_by: †, check_2_by: †}]
    notes: <discrepancies>
first_reviewer: †        # named human, date, qualification reference
second_reviewer: †       # required for values that become trusted references
status: draft | human_compared | unresolved | accepted_for_detection | rejected
```

† = filled only by the real person, never by a tool or an AI session. QĐ 1490 (V4) is the first candidate, and only
after the owner adopts this policy.
