-- Rollback of 20261106090000_rag_question_rate_limit.sql.
--
-- Before running it, set RAG_QA_RATE_LIMIT_STORE=memory (single API process only) or
-- RAG_QA_ENABLED=false on the API: with the default postgres store and the function gone,
-- every question is refused with 503 question_rate_limit_unavailable (fail closed).
-- Drops only per-user question timestamps (<= 24 h); no business data.

drop function if exists private.consume_rag_question_quota(uuid, integer, integer);
drop table if exists private.rag_question_events;
