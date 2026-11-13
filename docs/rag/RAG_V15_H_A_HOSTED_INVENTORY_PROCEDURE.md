# H-a hosted legacy inventory: read-only procedure (PREPARED, NOT RUN)

Status: **prepared only.** Nobody has connected to hosted for this. Running it needs a separate, explicit owner
authorization of this exact action. No migration, backfill or data repair is part of it.

## Queries

1. `docs/rag/sql/ha_legacy_inventory_summary.sql`: counts per category, no title or content:
   approved sources and approved documents per assurance (`verified`, `demo_unverified`, `unrecorded`);
   verified documents that would be withheld because their source is not verified; an upper bound of the
   served chunks H-a would withhold.
2. `docs/rag/sql/ha_legacy_approved_inventory.sql`: one row per version / source ever approved without an
   approve record (ids, status, hashes, artifact reference, chunk and event counts). Identifiers only.

Both derive the assurance from `knowledge_approval_records` the way the H-a backfill does, so they work
before H-a is applied (hosted today).

## Procedure (when authorized)

1. Use a **read-only** connection: a role with SELECT only, or the service credential inside an explicit
   read-only transaction. Never the owner login, never the migration tool.
2. Connect through the IPv4 session pooler (the direct host is IPv6-only); do not print the URL.
3. Run, in ONE transaction:
   ```sql
   begin transaction isolation level repeatable read read only;
   set local statement_timeout = '30s';
   set local idle_in_transaction_session_timeout = '60s';
   \i docs/rag/sql/ha_legacy_inventory_summary.sql
   \i docs/rag/sql/ha_legacy_approved_inventory.sql
   rollback;
   ```
   `read only` makes any write fail; `rollback` leaves nothing behind.
4. Save the two result sets to a local, non-committed file (ids are not secrets, but they are production
   identifiers); record the time, the database role and the row counts in the ticket.
5. Do not run H-a, the demo quarantine or any repair as a follow-up of the inventory; each is its own owner
   decision.

## Reading the result

- `approved documents / unrecorded` and `approved sources / unrecorded` are what H-a stops serving.
- `approved verified documents withheld by their unrecorded or demo source`: valid versions that disappear
  because of their source; remediation is per source (H-a document §2.4).
- `served chunks H-a would withhold (upper bound)`: the application impact; farmers' answers would cite
  fewer chunks or answer `insufficient_evidence` for those topics.
- `demo_unverified` on hosted would contradict D-H3a and must be reported to the owner immediately.
