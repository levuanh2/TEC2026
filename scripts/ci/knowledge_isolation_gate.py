#!/usr/bin/env python3
"""H-a isolation gate (docs/rag/RAG_V15_H_A_DEMO_ASSURANCE_ISOLATION.md, owner decision D-H3a).

Demo-approved knowledge may exist ONLY on an isolated local or dedicated test database. The database
cannot prove where it runs, so the gate has two halves:

  outside (this script, before it connects): the connection target must be a loopback or private
    address and must not be a Supabase-hosted endpoint;
  inside (private.knowledge_deployment_isolated(), on every read): the declaration row is bound to
    this cluster's system_identifier and database, and every account is on a reserved test domain.

Usage (database owner credentials of the LOCAL stack):
  python scripts/ci/knowledge_isolation_gate.py --db-url "$SUPABASE_DB_URL"            # check, print JSON
  python scripts/ci/knowledge_isolation_gate.py --db-url ... --declare "who / why"     # check, then declare
  python scripts/ci/knowledge_isolation_gate.py --db-url ... --revoke                  # back to shared

Exit 0 only when every check passes. Never run against a hosted project: it refuses before connecting.
The URL is never printed (it carries a password).
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from urllib.parse import urlsplit

HOSTED_SUFFIXES = (".supabase.co", ".supabase.com", ".supabase.net", ".supabase.in")
LOCAL_NAMES = {"localhost", "host.docker.internal"}
# Loopback and the RFC 1918 / ULA ranges a local or CI container network uses. Not ipaddress.is_private,
# which also accepts documentation and other special ranges.
LOCAL_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7"))


def target_refusal(db_url: str) -> str | None:
    """None when the target is a loopback/private address that is not a hosted endpoint, else why not."""
    try:
        parts = urlsplit(db_url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return "unparseable database URL"
    if parts.scheme not in ("postgres", "postgresql") or not host:
        return "not a postgres URL"
    if host.endswith(HOSTED_SUFFIXES) or "pooler" in host:
        return "a Supabase-hosted endpoint is never an isolated test database"
    if host in LOCAL_NAMES:
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return f"host {host!r} is a name that is not known to be local; use a loopback or private address"
    if any(address in network for network in LOCAL_NETWORKS if network.version == address.version):
        return None
    return f"address {host} is neither loopback nor private"


CHECK_SQL = """
select d.class, d.bound_system_identifier, d.bound_database, c.system_identifier, current_database(),
       private.knowledge_has_real_accounts(), private.knowledge_deployment_isolated(), d.attestation
  from private.knowledge_deployment d, pg_control_system() c
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db-url", required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--declare", metavar="ATTESTATION", help="who declares, and why this database is isolated")
    action.add_argument("--revoke", action="store_true", help="declare the database shared again")
    args = parser.parse_args(argv)

    refusal = target_refusal(args.db_url)
    if refusal is not None and not args.revoke:
        print(json.dumps({"gate": "REFUSED", "reason": refusal}))
        return 2
    import psycopg  # noqa: PLC0415 - only after the target check

    parts = urlsplit(args.db_url)
    with psycopg.connect(args.db_url) as conn:
        row = conn.execute(CHECK_SQL).fetchone()
        report = {"target": f"{parts.hostname}:{parts.port or 5432}", "class": row[0], "binding_matches":
                  row[1] == row[3] and row[2] == row[4], "system_identifier": str(row[3]), "database": row[4],
                  "real_accounts": row[5], "isolated": row[6]}
        if args.revoke:
            conn.execute("select private.knowledge_declare_shared()")
            report.update(action="revoked", isolated=conn.execute(
                "select private.knowledge_deployment_isolated()").fetchone()[0])
        elif args.declare:
            if row[5]:
                print(json.dumps({**report, "gate": "REFUSED", "reason": "accounts not on a reserved test domain"}))
                return 2
            attestation = (f"gate {parts.hostname}:{parts.port or 5432} sysid {row[3]} db {row[4]}: "
                           f"{args.declare.strip()}")[:2000]
            conn.execute("select private.knowledge_declare_isolated_test(%s)", (attestation,))
            report.update(action="declared", isolated=conn.execute(
                "select private.knowledge_deployment_isolated()").fetchone()[0])
    report["gate"] = "PASS" if report["isolated"] or args.revoke else "NOT_ISOLATED"
    print(json.dumps(report))
    return 0 if report["gate"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
