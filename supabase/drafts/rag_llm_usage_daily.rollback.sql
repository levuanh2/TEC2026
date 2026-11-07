-- DRAFT rollback of rag_llm_usage_daily.sql (not applied anywhere).
drop function if exists private.rag_llm_usage_reserve(date, text, integer, integer, numeric);
drop table if exists private.rag_llm_usage_daily;
