"""H-a: the external half of the isolation gate (scripts/ci/knowledge_isolation_gate.py). Pure: no
database, no network. Every URL is a synthetic fixture."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _gate():
    spec = importlib.util.spec_from_file_location("knowledge_isolation_gate", ROOT / "scripts/ci/knowledge_isolation_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


def test_the_gate_script_refuses_hosted_targets():
    """The connection target is checked before connecting."""
    gate = _gate()
    for url in ("postgresql://postgres:x@db.abcdefghijklmnopqrst.supabase.co:5432/postgres",
                "postgresql://postgres.ref:x@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres",
                "postgresql://postgres:x@203.0.113.7:5432/postgres",
                "postgresql://postgres:x@my-db.example.net:5432/postgres", "not a url",
                "postgresql://postgres:x@192.0.2.1:5432/postgres", "mysql://root@127.0.0.1/db"):
        assert gate.target_refusal(url) is not None, url
    for url in ("postgresql://postgres:postgres@127.0.0.1:54322/postgres",
                "postgresql://postgres:postgres@localhost:44522/postgres",
                "postgresql://postgres:postgres@[::1]:5432/postgres",
                "postgresql://postgres:postgres@172.19.0.6:5432/postgres"):
        assert gate.target_refusal(url) is None, url


def test_the_gate_refuses_before_connecting(capsys):
    """A hosted URL never reaches psycopg: the script exits 2 with the reason and no URL."""
    gate = _gate()
    url = "postgresql://postgres:secret-fixture@db.abcdefghijklmnopqrst.supabase.co:5432/postgres"
    assert gate.main(["--db-url", url, "--declare", "TEST FIXTURE attestation text"]) == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out and "secret-fixture" not in out and "supabase.co" not in out
