"""Test-harness guard: ordinary pytest never talks to a non-local database or Supabase API.

backend/.env holds the HOSTED project, and infrastructure.config.load_settings() fills every
ABSENT variable from it (os.environ.setdefault). Test modules call load_settings() at import,
so a run whose SUPABASE_* variables were merely unset (e.g. PowerShell `$env:X = ''` deletes X)
silently received the hosted database URL and connected to it.

`bootstrap()` runs before anything else in a test session: backend/pytest.ini loads this module
as the first pytest plugin (`-p tests._db_target`, ahead of entry-point plugins, PYTEST_PLUGINS
and every conftest), and tests/__init__.py runs it again for any `tests.*` import (--noconftest,
another ini, a test module imported outside pytest). It applies `enforce()` and then installs
connection-boundary guards (below):
- every target is classified by the host it would actually reach: SUPABASE_DB_URL through
  psycopg's own conninfo parser (multi-host lists, `?host=` / `hostaddr`, `service`, and the
  PGHOST / PGHOSTADDR / PGSERVICE / PGUSER fallbacks libpq applies independently); SUPABASE_URL
  and SUPABASE_JWKS_URL through urllib. Local = the name `localhost`, a loopback IP (127.0.0.0/8,
  ::1, ::ffff:127.x.x.x) or a Unix-socket directory. Nothing is matched by substring.
- a non-local target that comes from backend/.env is NEUTRALIZED for the session: every
  SUPABASE_* value taken from the file is set to "" (load_settings keeps "" -> None), which is
  exactly the CI no-DB state; DB tests skip by their existing gates and a warning is printed.
- a non-local target set explicitly in the process environment ABORTS the session (pytest prints
  the reason and exits with code 4, also while plugins are still loading).
- the only exception is an explicit, per-project opt-in from the process environment (never
  from .env): ALLOW_HOSTED_DB_TESTS=i-understand-this-touches-hosted AND
  AGRICARBON_HOSTED_TEST_PROJECT_REF=<20-char ref>, and then EVERY non-local target must be
  that project's exact Supabase endpoint (API `<ref>.supabase.co`; DB `postgres.<ref>` on a
  `*.pooler.supabase.com` host or `postgres` on `db.<ref>.supabase.co`). Anything else aborts.
Messages name variables and host kinds only, never credentials. Production settings
resolution (infrastructure/config.py) is not changed.
"""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, MutableMapping
from urllib.parse import urlsplit

from pytest import UsageError

DB_KEY = "SUPABASE_DB_URL"
HTTP_KEYS = ("SUPABASE_URL", "SUPABASE_JWKS_URL")
CREDENTIAL_KEYS = ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_PUBLISHABLE_KEY")
OPT_IN_KEY, OPT_IN_VALUE = "ALLOW_HOSTED_DB_TESTS", "i-understand-this-touches-hosted"
PROJECT_KEY = "AGRICARBON_HOSTED_TEST_PROJECT_REF"
_REF = re.compile(r"^[a-z0-9]{20}$")
BACKEND_DIR = Path(__file__).resolve().parent.parent


def read_dotenv(path: Path) -> dict[str, str]:
    """The same minimal parsing as infrastructure.config._load_dotenv, without touching os.environ."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def is_local_host(host: str) -> bool:
    host = host.strip()
    if host.startswith("/"):                          # a Unix-socket directory on this machine
        return True
    host = host.strip("[]")
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)    # ::ffff:127.0.0.1 is IPv4 loopback
    return address.is_loopback or bool(mapped and mapped.is_loopback)


def db_hosts(url: str, environ: Mapping[str, str]) -> tuple[list[str], str | None, bool]:
    """(hosts libpq would reach, user, uses a service file) for a PostgreSQL URL/conninfo."""
    try:
        from psycopg.conninfo import conninfo_to_dict
        params = conninfo_to_dict(url)
    except Exception:  # noqa: BLE001 -- unparsable: treat as unknown (= not local)
        return (["<unparsable>"], None, False)
    # libpq resolves `host` and `hostaddr` INDEPENDENTLY: each comes from the conninfo or else
    # from its own environment variable. `localhost` + PGHOSTADDR=<remote> connects remotely.
    host = params.get("host") or environ.get("PGHOST")
    hostaddr = params.get("hostaddr") or environ.get("PGHOSTADDR")
    hosts = [h for value in (host, hostaddr) if value for h in str(value).split(",")]
    # Only a selected service is used; PGSERVICEFILE / PGSYSCONFDIR merely say where to find one.
    service = bool(params.get("service") or environ.get("PGSERVICE"))
    user = params.get("user") or environ.get("PGUSER")
    return (hosts or ["/"], str(user) if user else None, service)


def classify_db(url: str, environ: Mapping[str, str]) -> str:
    hosts, _, service = db_hosts(url, environ)
    if service:
        return "service-file (unknown host)"
    if all(is_local_host(h) for h in hosts):
        return "local"
    if all(h.endswith(".pooler.supabase.com") for h in hosts):
        return "supabase-pooler"
    if all(re.fullmatch(r"db\.[a-z0-9]{20}\.supabase\.co", h) for h in hosts):
        return "supabase-direct"
    return "external"


def classify_http(url: str) -> str:
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return "external"
    if parts.scheme not in ("http", "https") or not host:
        return "external"
    if is_local_host(host):
        return "local"
    return "supabase-api" if re.fullmatch(r"[a-z0-9]{20}\.supabase\.co", host) else "external"


def matches_project(key: str, url: str, ref: str, environ: Mapping[str, str]) -> bool:
    if key == DB_KEY:
        hosts, user, service = db_hosts(url, environ)
        if service:
            return False
        pooler = user == f"postgres.{ref}" and all(h.endswith(".pooler.supabase.com") for h in hosts)
        direct = user == "postgres" and all(h == f"db.{ref}.supabase.co" for h in hosts)
        return pooler or direct
    try:
        return urlsplit(url).hostname == f"{ref}.supabase.co"
    except ValueError:
        return False


@dataclass
class Decision:
    action: str                                       # "ok" | "neutralize" | "abort" | "allow-hosted"
    reasons: list[str] = field(default_factory=list)
    neutralize: list[str] = field(default_factory=list)


def assess(environ: Mapping[str, str], dotenv: Mapping[str, str]) -> Decision:
    """Pure decision from the process environment and the parsed backend/.env."""
    remote_env, remote_dotenv = [], []
    for key in (DB_KEY, *HTTP_KEYS):
        if key in environ:
            source, value = "environment", environ[key]
        elif key in dotenv:
            source, value = "backend/.env", dotenv[key]
        else:
            continue
        if not value:
            continue
        kind = classify_db(value, environ) if key == DB_KEY else classify_http(value)
        if kind != "local":
            (remote_env if source == "environment" else remote_dotenv).append((key, value, kind, source))
    remote = remote_env + remote_dotenv
    if not remote:
        return Decision("ok")
    if environ.get(OPT_IN_KEY):
        ref = environ.get(PROJECT_KEY, "")
        if environ[OPT_IN_KEY] != OPT_IN_VALUE or not _REF.match(ref):
            return Decision("abort", [f"{OPT_IN_KEY} must be exactly {OPT_IN_VALUE!r} together with a valid "
                                      f"{PROJECT_KEY}; refusing the hosted run"])
        wrong = [f"{k} ({kind}, from {src}) is not project {ref}" for k, v, kind, src in remote
                 if not matches_project(k, v, ref, environ)]
        if wrong:
            return Decision("abort", wrong)
        return Decision("allow-hosted", [f"explicit hosted test run against project {ref}: "
                                         + ", ".join(k for k, *_ in remote)])
    if remote_env:
        return Decision("abort", [f"{k} in the process environment points at a non-local target ({kind}); "
                                  f"ordinary tests run against a LOCAL stack only" for k, _, kind, _ in remote_env])
    neutralize = [k for k in (DB_KEY, *HTTP_KEYS, *CREDENTIAL_KEYS) if k not in environ and k in dotenv]
    return Decision("neutralize", [f"{k} from backend/.env is a non-local target ({kind}); ignored for this "
                                   f"test session" for k, _, kind, _ in remote_dotenv], neutralize)


class RefusedTarget(ConnectionRefusedError):
    """Raised by the connection-boundary guards instead of opening a non-local connection."""


class RefusedSession(UsageError, RuntimeError):
    """The session is refused. A UsageError so pytest reports it and exits 4 even when raised
    while plugins load (backend/pytest.ini); a RuntimeError for every other importer."""


def enforce(environ: MutableMapping[str, str] | None = None, dotenv_path: Path | None = None) -> Decision:
    """Apply the decision to `environ` (default os.environ). Raises RefusedSession on abort."""
    environ = os.environ if environ is None else environ
    decision = assess(environ, read_dotenv(dotenv_path or BACKEND_DIR / ".env"))
    if decision.action == "abort":
        raise RefusedSession("refusing to run tests against a non-local target:\n  - " + "\n  - ".join(decision.reasons))
    for key in decision.neutralize:
        environ[key] = ""                             # load_settings' setdefault keeps "" -> None
    return decision


# ------------------------------------------------------------------ connection-boundary guards
# Defence in depth for every path that skips conftest (--noconftest, --confcutdir, a test module
# imported outside pytest): the effective target is re-checked at the moment a connection is
# made. psycopg (libpq uses C sockets) is wrapped at Connection.connect, which psycopg.connect and
# psycopg_pool use; every Python socket (Supabase/httpx clients, JWKS) is refused a non-loopback
# TCP destination. Not installed for an explicit, validated hosted run.

_INSTALLED: dict[str, object] = {}


def _socket_destination_is_local(address) -> bool:
    if not isinstance(address, tuple) or not address:
        return True                                   # AF_UNIX path or exotic family: local by nature
    return is_local_host(str(address[0]))


def install_connect_guards() -> None:
    if _INSTALLED:
        return
    import socket

    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def check(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _socket_destination_is_local(address):
            raise RefusedTarget(f"refused by the test DB target guard: non-loopback destination {address[0]}")

    def connect(self, address):
        check(self, address)
        return real_connect(self, address)

    def connect_ex(self, address):
        check(self, address)
        return real_connect_ex(self, address)

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
    _INSTALLED["socket"] = (real_connect, real_connect_ex)
    try:
        import psycopg
        from psycopg.conninfo import make_conninfo
    except ImportError:
        return
    real = psycopg.Connection.connect.__func__

    routing = ("host", "hostaddr", "port", "service", "user", "dbname")   # libpq params that pick the server

    def guarded(cls, conninfo: str = "", **kwargs):
        # psycopg's own keywords (autocommit, row_factory, prepare_threshold, ...) are not libpq params
        target = make_conninfo(conninfo, **{k: v for k, v in kwargs.items() if k in routing and v is not None})
        kind = classify_db(target, os.environ)
        if kind != "local":
            raise RefusedTarget(f"refused by the test DB target guard: non-local PostgreSQL target ({kind})")
        return real(cls, conninfo, **kwargs)

    psycopg.Connection.connect = classmethod(guarded)
    psycopg.connect = psycopg.Connection.connect
    _INSTALLED["psycopg"] = real


def bootstrap() -> Decision:
    """Called from tests/__init__.py, which every `tests.*` import runs first -- including this
    module's own import as the first pytest plugin (backend/pytest.ini). Idempotent."""
    decision = enforce()
    if decision.action != "allow-hosted":
        install_connect_guards()
    return decision
