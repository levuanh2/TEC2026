"""RAG V1.3-C knowledge ingestion foundation (docs/rag/RAG_V1_INGESTION.md).

Offline, operator-only pipeline: artifact bytes -> parser -> normalizer -> structure-aware
chunker -> stable ids -> KnowledgeStore. Everything here is pure (no database, network or
vendor SDK); the adapters live in infrastructure/knowledge_repo.py and the operator entry
point is backend/scripts/ingest_knowledge.py. Ingestion only ever creates `review_required`
rows -- approval is a separate, explicit human action. No embeddings, no vector, no LLM.
"""
