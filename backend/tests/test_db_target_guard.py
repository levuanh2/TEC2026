"""Ordinary pytest never falls back to the hosted database (tests/_db_target.py, tests/conftest.py).

Pure decision tests (A-H and spoofing), the end-to-end effect on the real load_settings(),
and connect-spy proofs: a pytest session pointed at a hosted/external target refuses BEFORE
psycopg.connect or any socket connect is attempted. No test here opens a network connection.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from tests import _db_target as guard  # noqa: E402

REF = "abcdefghijklmnopqrst"
POOLER = f"postgresql://postgres.{REF}:secret-pw@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"
DIRECT = f"postgresql://postgres:secret-pw@db.{REF}.supabase.co:5432/postgres"
LOCAL_DB = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
API = f"https://{REF}.supabase.co"
OPT_IN = {guard.OPT_IN_KEY: guard.OPT_IN_VALUE, guard.PROJECT_KEY: REF}
HOSTED_DOTENV = {"SUPABASE_URL": API, "SUPABASE_DB_URL": POOLER, "SUPABASE_JWKS_URL": API + "/auth/v1/.well-known/jwks.json",
                 "SUPABASE_SERVICE_ROLE_KEY": "service-secret", "SUPABASE_PUBLISHABLE_KEY": "publishable"}


# ------------------------------------------------------------------ A-H decisions

def test_a_no_db_url_is_the_ordinary_no_db_run():
    assert guard.assess({}, {}).action == "ok"
    assert guard.assess({"SUPABASE_DB_URL": ""}, {}).action == "ok"            # explicitly empty = no DB
    # an explicitly empty DB URL stays empty, but hosted API values from .env are still neutralized
    decision = guard.assess({"SUPABASE_DB_URL": ""}, HOSTED_DOTENV)
    assert decision.action == "neutralize" and "SUPABASE_DB_URL" not in decision.neutralize


def test_b_local_postgres_is_allowed():
    for url in (LOCAL_DB, "postgresql://postgres@localhost/postgres", "postgresql://u@[::1]:5432/db",
                "postgresql://u@127.4.5.6/db", "postgresql:///postgres?host=/var/run/postgresql"):
        assert guard.assess({"SUPABASE_DB_URL": url}, {}).action == "ok", url


@pytest.mark.parametrize(("url", "kind"), [(POOLER, "supabase-pooler"), (DIRECT, "supabase-direct"),
                                           ("postgresql://u:p@db.example.com:5432/x", "external")],
                         ids=["c-pooler", "d-direct", "e-external"])
def test_cde_non_local_targets_in_the_environment_abort(url, kind):
    decision = guard.assess({"SUPABASE_DB_URL": url}, {})
    assert decision.action == "abort" and kind in decision.reasons[0]
    assert "secret-pw" not in " ".join(decision.reasons)


def test_f_opt_in_with_the_wrong_project_or_value_aborts():
    wrong_ref = {**OPT_IN, guard.PROJECT_KEY: "zzzzzzzzzzzzzzzzzzzz"}
    assert guard.assess({"SUPABASE_DB_URL": POOLER, **wrong_ref}, {}).action == "abort"
    assert guard.assess({"SUPABASE_DB_URL": POOLER, guard.OPT_IN_KEY: "1", guard.PROJECT_KEY: REF}, {}).action == "abort"
    assert guard.assess({"SUPABASE_DB_URL": POOLER, guard.OPT_IN_KEY: guard.OPT_IN_VALUE}, {}).action == "abort"
    other_host = f"postgresql://postgres.{REF}:p@db.example.com:6543/postgres"           # right user, wrong host
    assert guard.assess({"SUPABASE_DB_URL": other_host, **OPT_IN}, {}).action == "abort"
    assert guard.assess({"SUPABASE_DB_URL": LOCAL_DB, "SUPABASE_URL": "https://evil.example", **OPT_IN}, {}).action == "abort"


def test_g_opt_in_with_the_expected_project_is_permitted_without_connecting(monkeypatch):
    monkeypatch.setattr("psycopg.connect", lambda *a, **k: pytest.fail("the guard connected"))
    env = {"SUPABASE_DB_URL": POOLER, "SUPABASE_URL": API, **OPT_IN}
    assert guard.assess(env, {}).action == "allow-hosted"
    assert guard.assess({"SUPABASE_DB_URL": DIRECT, **OPT_IN}, {}).action == "allow-hosted"
    assert guard.assess({}, {**HOSTED_DOTENV, guard.OPT_IN_KEY: guard.OPT_IN_VALUE,
                             guard.PROJECT_KEY: REF}).action == "neutralize"           # opt-in never from .env


def test_h_hosted_values_in_backend_env_are_neutralized_for_the_session():
    decision = guard.assess({}, HOSTED_DOTENV)
    assert decision.action == "neutralize"
    assert set(decision.neutralize) == set(HOSTED_DOTENV)
    mixed = guard.assess({"SUPABASE_DB_URL": LOCAL_DB}, HOSTED_DOTENV)        # local DB, hosted API from .env
    assert mixed.action == "neutralize" and "SUPABASE_DB_URL" not in mixed.neutralize and "SUPABASE_URL" in mixed.neutralize


def test_h_end_to_end_load_settings_never_sees_the_hosted_url(tmp_path, monkeypatch):
    """The real infrastructure.config.load_settings() after the guard ran on a hosted .env."""
    from infrastructure import config

    dotenv = tmp_path / ".env"
    dotenv.write_text("\n".join(f"{k}={v}" for k, v in HOSTED_DOTENV.items()), encoding="utf-8")
    env: dict[str, str] = {}
    guard.enforce(env, dotenv)
    monkeypatch.setattr(config.os, "environ", env)
    settings = config.load_settings(dotenv)
    assert settings.supabase_db_url is None and settings.supabase_url is None
    assert settings.supabase_service_role_key is None


# ------------------------------------------------------------------ spoofing / parsing

@pytest.mark.parametrize("url", [
    "postgresql://u:p@localhost.evil.example/db",
    "postgresql://u:p@127.0.0.1.nip.io/db",
    "postgresql://u:p@localhost/db?host=db.example.com",                 # libpq honours ?host=
    "postgresql://u:p@localhost/db?hostaddr=203.0.113.7",
    "postgresql://u:p@localhost,db.example.com/db",                      # multi-host list
    "postgresql://u:p@[2001:db8::1]/db",
    "postgresql://u:p@0.0.0.0/db",
    "postgresql:///db?service=prod",                                     # pg_service.conf: unknown host
    "host=db.example.com dbname=postgres",                               # keyword conninfo
    "not a url at all ://",
])
def test_spoofed_or_unknown_db_hosts_are_not_local(url):
    assert guard.assess({"SUPABASE_DB_URL": url}, {}).action == "abort", url


def test_libpq_environment_fallbacks_count(monkeypatch):
    hostless = "postgresql:///postgres"
    assert guard.assess({"SUPABASE_DB_URL": hostless}, {}).action == "ok"                # Unix socket
    assert guard.assess({"SUPABASE_DB_URL": hostless, "PGHOST": "db.example.com"}, {}).action == "abort"
    assert guard.assess({"SUPABASE_DB_URL": hostless, "PGSERVICE": "prod"}, {}).action == "abort"


@pytest.mark.parametrize("url", ["https://localhost@evil.example", "http://127.0.0.1.evil.example",
                                 f"https://{REF}.supabase.co.evil.example", "ftp://localhost", "https://"])
def test_spoofed_http_targets_are_not_local(url):
    assert guard.assess({"SUPABASE_URL": url}, {}).action == "abort", url


def test_local_http_targets_are_allowed():
    for url in ("http://127.0.0.1:54321", "http://localhost:54321", "http://[::1]:54321"):
        assert guard.assess({"SUPABASE_URL": url}, {}).action == "ok"


# ------------------------------------------------------------------ connect-spy proofs (real pytest sessions)

SPY = '''
import json, os, socket
log = os.environ["GUARD_SPY_LOG"]
def record(kind, target):
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps([kind, str(target)]) + "\\n")
_connect = socket.socket.connect
def connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if host not in ("127.0.0.1", "::1", "localhost"):
        record("socket", host)
    return _connect(self, address)
socket.socket.connect = connect
_create = socket.create_connection
def create_connection(address, *a, **k):
    if address[0] not in ("127.0.0.1", "::1", "localhost"):
        record("create_connection", address[0])
    return _create(address, *a, **k)
socket.create_connection = create_connection
try:
    import psycopg
    _pc = psycopg.connect
    def pc(*a, **k):
        record("psycopg.connect", "called")
        return _pc(*a, **k)
    psycopg.connect = pc
    psycopg.Connection.connect = classmethod(lambda cls, *a, **k: (record("psycopg.Connection.connect", "called"),
                                                                   _pc(*a, **k))[1])
except ImportError:
    pass
'''


def _session(tmp_path, env_overrides: dict[str, str], *test_args: str):
    spy_dir = tmp_path / "spy"
    spy_dir.mkdir()
    (spy_dir / "sitecustomize.py").write_text(SPY, encoding="utf-8")
    log = tmp_path / "connects.jsonl"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SUPABASE_", "PG", "ALLOW_HOSTED", "AGRICARBON_HOSTED"))}
    env.update({"PYTHONPATH": str(spy_dir), "GUARD_SPY_LOG": str(log), **env_overrides})
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", *test_args],
                          cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300)
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return proc, calls


@pytest.mark.parametrize("url", [POOLER, DIRECT, "postgresql://u:p@db.example.com/x"], ids=["pooler", "direct", "external"])
def test_a_hosted_target_in_the_environment_aborts_before_any_connect(tmp_path, url):
    proc, calls = _session(tmp_path, {"SUPABASE_DB_URL": url}, "tests/test_rag_knowledge_storage.py")
    assert proc.returncode == 4, proc.stdout[-500:] + proc.stderr[-500:]
    assert "refusing to run tests against a non-local target" in proc.stdout + proc.stderr
    assert "secret-pw" not in proc.stdout + proc.stderr
    assert calls == []                                   # psycopg.connect and socket connects: 0


def test_opt_in_with_a_wrong_project_aborts_before_any_connect(tmp_path):
    proc, calls = _session(tmp_path, {"SUPABASE_DB_URL": POOLER, guard.OPT_IN_KEY: guard.OPT_IN_VALUE,
                                      guard.PROJECT_KEY: "zzzzzzzzzzzzzzzzzzzz"}, "tests/test_rag_knowledge_storage.py")
    assert proc.returncode == 4 and calls == []


def test_the_spy_itself_sees_connects(tmp_path):
    """Control: the same harness records a real connect attempt (so `calls == []` above means something)."""
    probe = tmp_path / "probe_test.py"
    probe.write_text("import socket\n"
                     "def test_probe():\n"
                     "    s = socket.socket()\n"
                     "    s.settimeout(0.01)\n"
                     "    try:\n"
                     "        s.connect(('192.0.2.1', 9))\n"          # TEST-NET-1: never routed
                     "    except OSError:\n"
                     "        pass\n", encoding="utf-8")
    proc, calls = _session(tmp_path, {}, str(probe), "--rootdir", str(tmp_path))
    assert ["socket", "192.0.2.1"] in calls, proc.stdout[-300:]
