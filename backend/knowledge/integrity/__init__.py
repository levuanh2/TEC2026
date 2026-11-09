"""Offline source-integrity REVIEW AID (docs/rag/RAG_V15_SOURCE_INTEGRITY_OFFLINE.md).

Pure and deterministic: stdlib only, no database, network, provider or file system. Callers
pass bytes, texts and already-parsed registry data.

- provenance.py: evaluates supplied provenance metadata and evidence against artifact bytes.
- claims.py: conservative, rule-based extraction of checkable statements with exact spans.
- references.py: the versioned trusted-reference registry format and its validation.
- review.py: compares claims with each other and with the registry, and lists findings for
  a human expert.

Nothing here approves, rejects, quarantines or otherwise changes a knowledge status, and
nothing here is wired into retrieval or the answer path. A clean report is NOT evidence that
a document is true. It only means these deterministic checks found nothing. dev3-01 stays
open until the database-governed milestones (M1-M7) exist.
"""
