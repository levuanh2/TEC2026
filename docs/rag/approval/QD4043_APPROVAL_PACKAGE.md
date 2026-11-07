# Human approval package — QĐ 4043/QĐ-TTTV-TTBVTV (procedure annex)

Prepared 2026-11-07 for a **human approver**. Nothing has been approved or ingested anywhere;
this package only collects the evidence. Approval and ingestion remain separate operator actions.

## 1. Identity and artifact

| Field | Value |
|---|---|
| Title | Quy trình sản xuất lúa chất lượng cao và phát thải thấp vùng Đồng bằng sông Cửu Long |
| Issuer | Cục Trồng trọt và Bảo vệ thực vật (Bộ NN&MT) — *Kèm theo Quyết định số 4043/QĐ-TTTV-TTBVTV ngày 10/11/2025* |
| Artifact URL (HTTPS) | `https://storage-vnportal.vnpt.vn/cmu-khdn/5342/Vanban/quy-trinh-4043-qt-san-xuat-lua-clc-va-ptt-vung-dbscl-1.pdf` (Cà Mau extension-centre bucket; no issuer landing page found) |
| Bytes / SHA-256 | 465 721 B / `0aa5e2ee68cbf1d1448dc1a5a1f88173bafbf779457d8bfe80b10421fc64f1a2` — re-downloaded 2026-11-07, identical to the C1 record of 2026-10-07 |
| Signatures | 3 signatures, organisation certificate "CỤC TRỒNG TRỌT VÀ BẢO VỆ THỰC VẬT"; strict validation to the official Ban Cơ yếu G2 root with CRLs and trusted timestamps PASSED on 2026-10-07 (C1 provenance gate) |
| Number/date | blank in the text layer (drawn in the signature widgets); stamp glyphs + NAEC Bản tin Khuyến nông 07/2025 corroborate 4043 / 10-11-2025 |

## 2. Dry run (pinned pipeline)

`scripts/ingest_knowledge.py --dry-run` in `python:3.11.9-slim` + **pypdf 6.21.4 (the pinned
version)**, `--network none`, read-only mounts; run twice, byte-identical.
`normalized_sha256 3877af8a6cbb5be474eb49d592dec42ab2be9295f018f4f1f09ac3414cbfa92a`,
`parser_version kn-pdf-2+pypdf-6.21.4`, `kn-normalize-1`, `kn-chunk-1`, **16 chunks**; chunk ids and
section paths are identical to the pypdf 6.19 run (only the parser_version string differs).

| # | chunk_id | pages | section_path |
|---|---|---|---|
| 0 | 9ae48b18bae61b6f65ef | 1 | VÙNG ĐỒNG BẰNG SÔNG CỬU LONG |
| 1–2 | bf2a7fada837cb1ffa4e, 02f3d9180a98ec715b7d | 1–2 | I. GIỚI THIỆU CHUNG |
| 3 | 98acd9a0bfa2d9f2b34d | 2 | II. NỘI DUNG QUY TRÌNH > 1. Kỹ thuật canh tác |
| 4 | 6efca8a43a9ceb1ca2ef | 2 | … > 1.1. Làm đất |
| 5 | e16f4ecbe555f1bc2abb | 2 | … > 1.2. Chuẩn bị giống |
| 6 | 6ee21c55a078257c724d | 3 | … > 1.3. Gieo sạ |
| 7 | 1f2480121aef0969214d | 3–4 | … > 1.4. Quản lý nước giảm phát thải khí (AWD) |
| 8–9 | c68ddaf8ae4b84b7f967, b9474fc34187f90ceb04 | 4–5 | … > 1.5. Bón phân |
| 10 | 727450ca9229d95f1929 | 5 | … > 1.6. Phòng, chống sinh vật gây hại lúa |
| 11–12 | adf672d23b2ce3f2f7b6, d5251204a852d7c932bf | 5–6 | II. … > 2. Quản lý thu hoạch và xử lý sau thu hoạch |
| 13–15 | a8d4341b7f3bd40a4419, 8c0bbfb6b53cfa4ca11b, 707b620115ea9cee57d1 | 6–8 | II. … > 3. Quản lý rơm rạ |

The earlier section-path blocker (harvest and straw chunks citing "1.6 Phòng, chống sinh vật") is
**resolved** by kn-pdf-2 (#30). Pipeline warnings: `license_basis unknown` (§3), 7 repeated
header/footer lines removed.

## 3. Decisions the approver must record (not made here)

1. **License basis.** Proposed for confirmation: `official_publication` — the annex is part of an
   administrative decision of a state agency; Luật Sở hữu trí tuệ Điều 15 excludes văn bản hành chính
   from copyright protection. A human (or legal) confirmation is required; record it as
   `license_reference`.
2. **Completeness / effectivity.** The artifact is the procedure annex only; the decision page
   (Điều 1–3, effective date, signer, relation to QĐ 145/QĐ-TT-CLT of 27/3/2024) is absent. The
   annex says QĐ 145 is "rà soát, sửa đổi và bổ sung" (not "thay thế"); QĐ 145's status is unknown.
   Decide: approve as the annex with this limitation in `review_note`, or wait for the decision page
   from the issuer.
3. **Internal conflict — straw.** Prose, p.7 (chunk 14/15): *"Vụ Đông Xuân: Cày/xới vùi gốc rạ ngay
   sau thu hoạch (càng sớm càng tốt), duy trì điều kiện khô (không ngập nước) tối thiểu 2 tuần sau
   khi vùi"*. The image-only diagram on p.7 states "ít nhất 3 tuần" (C1 record) and is NOT in any
   chunk, so the corpus would carry only "2 tuần". Record the conflict in `review_note`; ask the
   issuer which applies before any answer quotes a duration.
4. **Scope of use.** No emission factors are in this document (no SF, GWP, MRV figures): it may be
   cited for practices (AWD water management, fertilizer timing, straw), never as a Carbon source.

## 4. Steps after a human approval (operator, never automatic)

1. Local / staging only first: run the same command with `--target local` (writes
   `review_required` rows + the artifact at `knowledge-artifacts/<file_sha256>/qd4043.pdf`).
2. Re-verify: download the stored object, SHA-256 == `file_sha256` (`knowledge_repo.verify`); run
   the zero-orphan audit SQL of RAG_V1_INGESTION.md §5.
3. Set `approved` with the approver's identity, `license_basis`, `license_reference` and the
   `review_note` of §3, as a separate SQL step by the approver.
4. Hosted: a one-document gate with explicit owner approval (not part of V1.5).
