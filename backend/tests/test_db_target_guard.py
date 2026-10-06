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
    assert guard.assess({"SUPABASE_DB_URL": hostless, "PGSERVICE": "prod", "PGSERVICEFILE": "/tmp/x"}, {}).action == "abort"
    # PGSERVICEFILE only says where a service file is; without a selected service libpq ignores it
    assert guard.assess({"SUPABASE_DB_URL": hostless, "PGSERVICEFILE": "/tmp/x"}, {}).action == "ok"
    assert guard.assess({"SUPABASE_DB_URL": DIRECT, "PGSERVICEFILE": "/tmp/x", **OPT_IN}, {}).action == "allow-hosted"


def test_hosted_identity_uses_the_libpq_pguser_fallback():
    userless = POOLER.replace(f"postgres.{REF}:secret-pw@", "")
    assert guard.assess({"SUPABASE_DB_URL": userless, "PGUSER": f"postgres.{REF}", **OPT_IN}, {}).action == "allow-hosted"
    assert guard.assess({"SUPABASE_DB_URL": userless, "PGUSER": "postgres.zzzzzzzzzzzzzzzzzzzz", **OPT_IN}, {}).action == "abort"
    assert guard.assess({"SUPABASE_DB_URL": userless, **OPT_IN}, {}).action == "abort"          # OS user: unknown
    # an explicit user in the URL wins over PGUSER, as in libpq
    assert guard.assess({"SUPABASE_DB_URL": POOLER.replace(f"postgres.{REF}", "someone"),
                         "PGUSER": f"postgres.{REF}", **OPT_IN}, {}).action == "abort"


def test_ipv4_mapped_loopback_is_local_and_other_mapped_addresses_are_not():
    assert guard.is_local_host("::ffff:127.0.0.1") and guard.is_local_host("[::ffff:127.9.9.9]")
    assert not guard.is_local_host("::ffff:203.0.113.7")
    assert guard.assess({"SUPABASE_DB_URL": "postgresql://u@[::ffff:127.0.0.1]:5432/db",
                         "SUPABASE_URL": "http://[::ffff:127.0.0.1]:54321"}, {}).action == "ok"
    assert guard.assess({"SUPABASE_DB_URL": "postgresql://u@[::ffff:203.0.113.7]/db"}, {}).action == "abort"


def test_a_refused_session_is_a_pytest_usage_error_and_a_runtime_error():
    with pytest.raises(guard.RefusedSession) as err:
        guard.enforce({"SUPABASE_DB_URL": POOLER}, Path("does-not-exist.env"))
    assert isinstance(err.value, pytest.UsageError) and isinstance(err.value, RuntimeError)
    assert "secret-pw" not in str(err.value)


@pytest.mark.parametrize("env", [
    {"PGHOSTADDR": "203.0.113.7"},                        # libpq: host=localhost, hostaddr from the environment
    {"PGHOSTADDR": "127.0.0.1,203.0.113.7"},
    {"PGHOST": "db.example.com"},                         # host-less URL below
], ids=["hostaddr", "hostaddr-list", "pghost"])
def test_libpq_host_and_hostaddr_resolve_independently(env):
    url = "postgresql://u@localhost/db" if "PGHOSTADDR" in env else "postgresql://u@/db"
    assert guard.assess({"SUPABASE_DB_URL": url, **env}, {}).action == "abort"
    assert guard.assess({"SUPABASE_DB_URL": "postgresql://u@localhost/db", "PGHOSTADDR": "127.0.0.1"}, {}).action == "ok"


# ------------------------------------------------------------------ connection-boundary guards (this session)

def test_this_session_refuses_a_non_local_psycopg_target_before_libpq(monkeypatch):
    import psycopg

    assert guard._INSTALLED, "tests/__init__.py installs the guards for every test session"
    for target in ("postgresql://u:secret-pw@db.example.com/x", POOLER, "host=203.0.113.7 dbname=x"):
        with pytest.raises(guard.RefusedTarget) as err:
            psycopg.connect(target, connect_timeout=1)
        assert "secret-pw" not in str(err.value)
    monkeypatch.setenv("PGHOSTADDR", "203.0.113.7")         # the environment is re-read at connect time
    with pytest.raises(guard.RefusedTarget):
        psycopg.connect("postgresql://u@localhost/x", connect_timeout=1)
    with pytest.raises(guard.RefusedTarget):
        psycopg.Connection.connect("postgresql://u@db.example.com/x")
    with pytest.raises(guard.RefusedTarget):                    # a keyword host overrides a local conninfo
        psycopg.connect("postgresql://u@localhost/x", host="db.example.com", autocommit=True)


def test_this_session_refuses_non_loopback_sockets_and_keeps_loopback():
    import socket

    with socket.socket() as s, pytest.raises(guard.RefusedTarget):
        s.connect(("192.0.2.1", 9))
    with socket.socket() as s, pytest.raises(guard.RefusedTarget):
        s.connect_ex(("192.0.2.1", 9))
    with pytest.raises(guard.RefusedTarget):
        socket.create_connection(("192.0.2.1", 9), timeout=1)
    with socket.socket() as s:
        s.settimeout(1)
        assert s.connect_ex(("127.0.0.1", 9)) != 0              # an ordinary refusal, not the guard


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


def _session(tmp_path, env_overrides: dict[str, str], *test_args: str, cwd: Path = BACKEND, command=None):
    spy_dir = tmp_path / "spy"
    spy_dir.mkdir(exist_ok=True)
    (spy_dir / "sitecustomize.py").write_text(SPY, encoding="utf-8")
    log = tmp_path / "connects.jsonl"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SUPABASE_", "PG", "ALLOW_HOSTED", "AGRICARBON_HOSTED"))}
    env.update({"PYTHONPATH": str(spy_dir), "GUARD_SPY_LOG": str(log), **env_overrides})
    command = command or [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", *test_args]
    proc = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return proc, calls


@pytest.mark.parametrize("url", [POOLER, DIRECT, "postgresql://u:p@db.example.com/x"], ids=["pooler", "direct", "external"])
def test_a_hosted_target_in_the_environment_aborts_before_any_connect(tmp_path, url):
    proc, calls = _session(tmp_path, {"SUPABASE_DB_URL": url}, "tests/test_rag_knowledge_storage.py")
    assert proc.returncode == 4, proc.stdout[-500:] + proc.stderr[-500:]
    assert "refusing to run tests against a non-local target" in proc.stdout + proc.stderr
    assert "secret-pw" not in proc.stdout + proc.stderr
    assert calls == []                                   # psycopg.connect and socket connects: 0


REFUSAL = "refusing to run tests against a non-local target"
HOSTED_ENV = {"SUPABASE_DB_URL": POOLER}


@pytest.mark.parametrize("extra", [["--noconftest"], ["--confcutdir", "tests/fixtures"]], ids=["noconftest", "confcutdir"])
def test_conftest_bypasses_still_refuse_before_any_connect(tmp_path, extra):
    proc, calls = _session(tmp_path, HOSTED_ENV, "tests/test_rag_knowledge_storage.py", *extra)
    assert proc.returncode != 0 and REFUSAL in proc.stdout + proc.stderr
    assert "secret-pw" not in proc.stdout + proc.stderr and calls == []


def test_invocation_from_the_repository_root_refuses(tmp_path):
    proc, calls = _session(tmp_path, HOSTED_ENV, "backend/tests/test_rag_knowledge_storage.py", cwd=BACKEND.parent)
    assert proc.returncode != 0 and REFUSAL in proc.stdout + proc.stderr and calls == []


def test_importing_a_test_module_outside_pytest_refuses(tmp_path):
    proc, calls = _session(tmp_path, HOSTED_ENV,
                           command=[sys.executable, "-c", "import tests.test_rag_knowledge_storage"])
    assert proc.returncode != 0 and REFUSAL in proc.stderr and calls == []


def test_a_local_url_with_a_remote_pghostaddr_refuses_before_any_connect(tmp_path):
    proc, calls = _session(tmp_path, {"SUPABASE_DB_URL": LOCAL_DB.replace("127.0.0.1", "localhost"),
                                      "PGHOSTADDR": "203.0.113.7"}, "tests/test_rag_knowledge_storage.py")
    assert proc.returncode != 0 and REFUSAL in proc.stdout + proc.stderr and calls == []


def test_opt_in_with_a_wrong_project_aborts_before_any_connect(tmp_path):
    proc, calls = _session(tmp_path, {"SUPABASE_DB_URL": POOLER, guard.OPT_IN_KEY: guard.OPT_IN_VALUE,
                                      guard.PROJECT_KEY: "zzzzzzzzzzzzzzzzzzzz"}, "tests/test_rag_knowledge_storage.py")
    assert proc.returncode == 4 and calls == []


# A plugin that loads before tests/ and tries to connect while pytest is still loading plugins.
# It never imports `tests` (that would run the guard itself) and only targets TEST-NET addresses.
EARLY_PLUGIN = '''
import json, os, socket
from urllib.parse import urlsplit
def note(*item):
    with open(os.environ["GUARD_EARLY_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(item) + "\\n")
note("loaded")
try:
    from infrastructure.config import load_settings
    url = load_settings().supabase_db_url
    note("settings-db", "none" if not url else
         "local" if urlsplit(url).hostname in ("127.0.0.1", "localhost") else "NON-LOCAL")
except Exception as exc:
    note("settings-db", type(exc).__name__)
def pg():
    import psycopg
    psycopg.connect("postgresql://u:secret-pw@203.0.113.7:5432/x", connect_timeout=1)
for name, attempt in (("psycopg", pg), ("socket", lambda: socket.create_connection(("192.0.2.1", 9), timeout=0.5))):
    try:
        attempt()
        note(name, "connected")
    except Exception as exc:
        note(name, type(exc).__name__)
if os.environ.get("GUARD_EARLY_STOP"):                # end the session before collection
    import pytest
    raise pytest.UsageError("early probe done")
'''
EARLY_LOADERS = ["entry-point", "PYTEST_PLUGINS", "command-line -p"]
PURE_TEST = "tests/test_db_target_guard.py::test_a_no_db_url_is_the_ordinary_no_db_run"


def _early_plugin_session(tmp_path, loader: str, env: dict[str, str], *extra: str, cwd: Path = BACKEND,
                          test_path: str | None = PURE_TEST):
    spy_dir = tmp_path / "spy"
    spy_dir.mkdir()
    (spy_dir / "early_probe_plugin.py").write_text(EARLY_PLUGIN, encoding="utf-8")
    log = tmp_path / "early.jsonl"
    env = {**env, "GUARD_EARLY_LOG": str(log), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": ""}
    args = [*extra, *([test_path] if test_path else [])]
    if loader == "entry-point":                       # an installed distribution's pytest11 entry point
        dist = spy_dir / "early_probe-0.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: early-probe\nVersion: 0\n", encoding="utf-8")
        (dist / "entry_points.txt").write_text("[pytest11]\nearly_probe = early_probe_plugin\n", encoding="utf-8")
    elif loader == "PYTEST_PLUGINS":
        env["PYTEST_PLUGINS"] = "early_probe_plugin"
    else:
        args = ["-p", "early_probe_plugin", *args]
    proc, calls = _session(tmp_path, env, *args, cwd=cwd)
    notes = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return proc, calls, notes


@pytest.mark.parametrize("loader", EARLY_LOADERS)
def test_a_plugin_loaded_before_the_tests_cannot_connect(tmp_path, loader):
    """backend/pytest.ini loads the guard ahead of every other plugin: the early plugin's psycopg
    and socket attempts are refused at the boundary, and load_settings() no longer sees the
    hosted backend/.env (where one exists, it is already neutralized)."""
    proc, calls, notes = _early_plugin_session(tmp_path, loader, {})
    out = proc.stdout[-800:] + proc.stderr[-800:]
    assert proc.returncode == 0, out
    assert ["loaded"] in notes, out                       # the probe really ran as a plugin
    assert ["psycopg", "RefusedTarget"] in notes and ["socket", "RefusedTarget"] in notes, notes
    assert next(n for n in notes if n[0] == "settings-db")[1] in ("none", "local"), notes
    # the spy logs create_connection when it is CALLED; the connects themselves never happened
    assert [c for c in calls if c[0] != "create_connection"] == [], calls


@pytest.mark.parametrize("loader", EARLY_LOADERS)
def test_a_hosted_target_refuses_the_session_before_an_early_plugin_loads(tmp_path, loader):
    proc, calls, notes = _early_plugin_session(tmp_path, loader, HOSTED_ENV)
    assert proc.returncode == 4 and REFUSAL in proc.stdout + proc.stderr, proc.stdout[-500:] + proc.stderr[-500:]
    assert "secret-pw" not in proc.stdout + proc.stderr
    assert notes == [] and calls == []


def test_a_bare_pytest_from_the_repository_root_loads_the_guard_first(tmp_path):
    """No test path: the root pytest.ini (not backend/pytest.ini) is the config; the guard still
    loads before an early plugin. The probe ends the session before collecting the whole repo."""
    proc, calls, notes = _early_plugin_session(tmp_path, "PYTEST_PLUGINS", {"GUARD_EARLY_STOP": "1"},
                                               cwd=BACKEND.parent, test_path=None)
    out = proc.stdout[-800:] + proc.stderr[-800:]
    assert proc.returncode == 4 and "early probe done" in out, out
    assert ["loaded"] in notes and ["psycopg", "RefusedTarget"] in notes and ["socket", "RefusedTarget"] in notes, notes
    assert next(n for n in notes if n[0] == "settings-db")[1] in ("none", "local"), notes
    assert [c for c in calls if c[0] != "create_connection"] == [], calls
    (tmp_path / "hosted").mkdir()
    proc, calls, notes = _early_plugin_session(tmp_path / "hosted", "PYTEST_PLUGINS", HOSTED_ENV,
                                               cwd=BACKEND.parent, test_path=None)
    assert proc.returncode == 4 and REFUSAL in proc.stdout + proc.stderr and notes == [] and calls == []


def test_without_the_ini_plugin_the_early_probe_does_connect(tmp_path):
    """Control: with pytest.ini's `-p tests._db_target` overridden away, the same probe's attempts
    reach the (never-routed TEST-NET) targets -- so the zero-connect results above mean something."""
    proc, calls, notes = _early_plugin_session(tmp_path, "PYTEST_PLUGINS", {}, "-o", "addopts=")
    assert ["loaded"] in notes and ["psycopg", "RefusedTarget"] not in notes, notes
    assert ["psycopg.connect", "called"] in calls and ["socket", "192.0.2.1"] in calls, calls


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
