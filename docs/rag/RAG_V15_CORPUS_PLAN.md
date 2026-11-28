# RAG V1.5 / L2 — Agricultural knowledge corpus plan

Status: **PLAN. Nothing in this file is approved, ingested or labelled.** No hosted ingestion without a separate
owner approval. This file lists no reference that has not been obtained and hashed. Where it names an institution,
that is *where to look*, not a claim that a given document exists.

## 1. Rules (from `RAG_V1_SOURCE_POLICY.md`, applied to every candidate)
1. **Never invent provenance.** An unknown author, year, version, URL or licence stays empty, and the document is not approvable.
2. Each version records:
   - its bytes and their SHA-256 (ST1 / ST1.1);
   - the official URL it came from;
   - the issuer as printed;
   - `published_at` only if the document states it;
   - `license_basis` ≠ `unknown`, plus `license_reference` for `open_license` / `written_permission`.
3. **Scope of application**: crop, region (e.g. ĐBSCL), season and practice, written in the version's review note. It is
   later used as a condition tag (M5), so an answer for a Northern farm does not cite a Mekong-only procedure.
4. **Rights decide eligibility before content does.** A document whose rights are unclear stays out of the corpus. It
   can still be read by a human as background.
5. A text layer is required: no OCR in V1.3 (scan-only documents are refused by the pipeline, e.g. QĐ 1490).
6. Approval needs a real, named expert (E4) and verified approval (M2/E2/E7). Until E4, the local corpus is used
   for engineering and evaluation only.

## 2. What already exists (verified in the repo, `RAG_V15_E1_EVIDENCE_ACQUISITION_2026_11_17.md` on #85)
| ID | Document | Usable for the corpus? |
|---|---|---|
| A-01, A-02 | IPCC 2019 Refinement, Vol. 4 Ch. 5 (Cropland) and Ch. 11 (N2O, lime, urea) | Content: yes, methodology. **Rights: the front matter carries an IPCC copyright notice and no reproduction terms** → needs IPCC permission before chunk text is served (`RAG_V15_E1_RIGHTS_AND_OCR.md`) |
| A-04, A-05 | IPCC 2006 Vol. 4 Ch. 2; AR5 WG1 Ch. 8 | same rights question |
| A-06, A-07 | UNFCCC decisions 18/CMA.1, 5/CMA.3 (UN documents) | reporting rules; rights to check on the UN terms page |
| A-08 | QĐ 2626/QĐ-BTNMT (emission-factor list), complete, signed | Vietnamese administrative decision. Likely outside copyright protection (Luật SHTT, documents of state bodies); **to confirm with the owner's legal reading** |
| A-09 | QĐ 4801/QĐ-BNNMT | cover/decision page only, no MRV annex → not enough |
| A-10 | QĐ 4043 annex (Mekong high-quality, low-emission rice procedure) | provenance PASS (signed annex); open section-path blocker |
| A-11 | QĐ 1490/QĐ-TTg | scan-only → refused (no OCR) |

## 3. Coverage plan by topic (owner list)
For each topic: what must be found, where to look first, and the evidence type. Every row starts at **0 approved documents**.

| Topic | What the corpus must answer | Look first at (institutions; verify each document) | Evidence type |
|---|---|---|---|
| Rice (lúa) | water regimes / AWD, "1 phải 5 giảm", seed, sowing density, CH4 | Cục Trồng trọt và BVTV; Viện Lúa ĐBSCL; IRRI; FAO; QĐ 4043 annex (A-10) | technical procedure, research |
| Vegetables (rau màu) | crop calendars, fertiliser, irrigation, safe pesticide use (principles only) | Cục Trồng trọt và BVTV; provincial agricultural extension centres; FAO | procedure, extension guide |
| Fruit trees (cây ăn trái) | nutrition, irrigation, flowering management | Viện Cây ăn quả miền Nam; universities (e.g. ĐH Cần Thơ); FAO | research, procedure |
| Industrial crops (cây công nghiệp) | coffee, pepper, rubber: nutrition, water, emissions | Viện KHKT Nông Lâm nghiệp Tây Nguyên; NAEC coffee/rice book (rights ambiguous, §4) | procedure |
| Soil (đất) | soil type, pH, organic matter, salinity (ĐBSCL) | Viện Thổ nhưỡng Nông hóa; FAO soils portal | research, guidance |
| Irrigation water (nước tưới) | AWD rules, water volume records, salinity | IRRI; Cục Thủy lợi; QĐ 4043 annex | procedure |
| Fertiliser / nutrition | N-P-K rates by crop and season, split application | Viện Thổ nhưỡng Nông hóa; university theses with a stated licence | research |
| Pests and diseases (sâu bệnh) | identification and IPM **principles only** (L1/L3 never prescribe products or doses) | Cục BVTV (the clean letter on rice weeds, C1 inventory); FAO IPM | official guidance |
| Yield (năng suất) | yield ranges by region and season, as context | statistical yearbooks; research | statistics |
| Carbon emissions | CH4 (rice), N2O (fertiliser), CO2 (lime, urea, fuel); factors and methods | A-01, A-02, A-04, A-08 (QĐ 2626) | methodology, official factors |

## 4. Acquisition procedure (per document)
1. Find it on the publisher's own site, over HTTPS (not a mirror). Record the URL.
2. Download it, hash it, and check whether there is a text layer.
3. Record issuer, title, number and date **as printed**. For a VN e-signed PDF, number and date may live in signature widgets
   (`vn_esigned_pdf_blank_number_date`); read them there.
4. Rights: find the licence statement in the document or on the publisher's terms page and quote it. No statement → `unknown` → not approvable.
5. Scope of application: crop, region, season.
6. Run the C1 quick artifact prefilter, then the full C1 gate (local) before anything is proposed for approval.
7. Ingest **locally only** (`ingest_knowledge.py` against the local stack). A hosted ingestion is a separate owner approval.

## 5. Owner decisions this plan needs
- D-C1: may IPCC text be served as chunk content without written permission (the current answer is no)? Or should we request permission?
- D-C2: legal reading of Vietnamese administrative decisions (QĐ 2626, QĐ 4043) as outside copyright protection.
- D-C3: the first expert (E4) who will review and approve the first rice + carbon slice.
- D-C4: the first slice: suggested **rice water regime + CH4 + fertiliser N2O**, because the existing engine and the L1 data cover it.
