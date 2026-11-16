# RAG V1.5 E1: IPCC copyright page, search-indexed text (evidence record)

Status: **EVIDENCE ONLY, 2026-11-16. Not a rights clearance. E1 OPEN, E4 OPEN, dev3-01 OPEN.**

This file adds no code, corpus document, registry entry, engine factor or table reproduction. It is independent of
the E1/E4 plan (Draft PR #82) and of the READ-tier citation code PR, and changes neither. When #82 is reviewed, its
rights document (`RAG_V15_E1_RIGHTS_AND_OCR.md` §2.1, §2.3) can point here; this file does not edit it.

## 1. What was retrieved, how, and when

| Item | Value |
|---|---|
| Primary page | `https://www.ipcc.ch/copyright/` (title in the index: "Copyright — IPCC") |
| Live fetch | **failed**: `HTTP 403 text/html` at 2026-11-16T15:57Z (one automated request, browser user agent). The same 403 was recorded on 2026-11-12 and earlier on 2026-11-16 |
| Source of the text below | a web search engine's index of that URL, two queries, 2026-11-16 (about 15:50–15:57 UTC) |
| Saved copy of the live page | none (it could not be fetched) |
| SHA-256 of the page | none (no bytes were obtained) |

**No live fetch succeeded.** The text in §2 is how the search index renders the page. It is not a copy of the page.

## 2. Indexed text attributed to `https://www.ipcc.ch/copyright/`

The sentences below are quoted as the search index returned them. They were not compared with the live page.

1. Personal use: "You may freely download and copy the material contained on this website for your personal,
   non-commercial use, without any right to resell or redistribute it or to compile or create derivative works there
   from."
2. Excerpts: "Reproduction of limited number of figures or short excerpts of IPCC material is authorized free of
   charge and without formal written permission provided that the original source is properly acknowledged".
3. Exactness: figures may not be altered; "permission can only be granted to use the material exactly as it is in the
   report" (index wording).
4. Linking: any external website may link to the IPCC website or any of its pages without asking permission (index
   paraphrase).
5. Other uses: "For any other use, permission is required. To obtain permission, please email a scanned copy of a
   letter on official letterhead addressed to the Secretary of the IPCC with all relevant details. Responses may take
   up to four weeks." The index gives the address as `copyright@ipcc.ch`.

The index also returned an **older archived page**, `https://archive.ipcc.ch/home_copyright.shtml`, which it says asked
for a signed letter by fax (+41 22 730 8025). That archived page also answered 403 to automated access. Its wording is
superseded and is not used here.

## 3. Limitations (read before relying on §2)

- **Not verified against the page.** Index text can be stale, truncated, reordered or paraphrased. Items 3 and 4 are
  partly paraphrased by the index itself.
- **No version or date for the page.** We do not know when the index last crawled it, or whether the page has changed.
- **Report-specific terms can differ.** The same searches show other terms inside some reports. One WG II volume
  requires Cambridge University Press's written permission for any reproduction. Some Cambridge editions are
  CC BY-NC-ND 4.0 with third-party content excluded. The 2019 Refinement front matter and download page still have to
  be checked for their own terms (#82 rights document §2.2).
- **Third-party content** inside IPCC reports (figures, tables, maps) needs permission from its own rights holders.

## 4. What this does NOT establish

- **No owner rights clearance.** Clearance step 1 (#82 rights document §2.5) still requires a person to read the
  official page in a browser and record it with a date and a saved copy plus SHA-256. The owner then has to decide
  per intended use.
- **No permission for this project's uses.** Even as indexed, the terms say that compiling or creating derivative works
  (item 1) and "any other use" (item 5) need permission. Neither a retrieval corpus nor systematic transcription of
  tables is shown to fall under the short-excerpt allowance (item 2). Whether they do is a question for the owner,
  and for counsel if needed.
- **Nothing is authorized.** This record permits no reproduction of IPCC tables, ingestion into the knowledge corpus,
  scientific verification, registry promotion, or change to engine factors (`backend/config/emission_factors.yaml`).
- **Existing repository exposure is unchanged.** The decision on the IPCC-derived content already committed (#82
  rights document §2.4) remains the owner's.

## 5. Next steps (owner)

1. A person opens `https://www.ipcc.ch/copyright/` in a browser, then saves the page outside Git with its SHA-256 and
   the date.
2. Compare the saved page with §2; record any difference.
3. Check the 2019 Refinement's own front matter for report-specific terms.
4. Decide each intended use (#82 rights document §2.5). Where needed, write to the IPCC Secretariat as the page directs.

Sources (search index, 2026-11-16): `https://www.ipcc.ch/copyright/`, `https://archive.ipcc.ch/home_copyright.shtml`,
`https://assets.cambridge.org/97810091/57957/copyright/9781009157957_copyright_info.pdf` (listed by the index, not
fetched).
