# Acknowledged migration data changes

`scripts/ci/migration_upgrade.sh` seeds a database at the base revision, applies
the new migrations, and fails with `MIGRATION_DATA_CHANGED` when any table that
existed at the base loses, duplicates or rewrites rows (row count + checksum of
the base columns). A reviewed, intentional backfill is allowed by adding one
exact line per migration and table:

    ACK data-change <migration file name> <table>

Adding a line here is a CI-policy change: reviewers must check the migration's
data effect, not just its syntax.

## Acknowledgements

(none)
