-- Rollback for migrations/20261110090000_knowledge_status_m1_values.sql.
-- PostgreSQL cannot drop an enum value, so there is nothing to run here. Roll back M1 with
-- 20261110090100_knowledge_status_lifecycle_m1.down.sql. It refuses while any row uses
-- expert_review / quarantined, and afterwards the restored Migration A triggers make both
-- values unreachable. Then: supabase migration repair --status reverted 20261110090000
select 1;
