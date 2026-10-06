"""Test-harness guard: ordinary pytest never talks to a non-local database or Supabase API.

backend/.env holds the HOSTED project, and infrastructure.config.load_settings() fills every
ABSENT variable from it (os.environ.setdefault). Test modules call load_settings() at import,
so a run whose SUPABASE_* variables were merely unset (e.g. PowerShell `$env:X = ''` deletes X)
silently received the hosted database URL and connected to it.

tests/conftest.py calls `enforce()` before any test module is imported:
- every target is classified by the host it would actually reach: SUPABASE_DB_URL through
  psycopg's own conninfo parser (multi-host lists, `?host=` / `hostaddr`, `service`, and the
  PGHOST / PGHOSTADDR / PGSERVICE fallbacks libpq applies to a host-less URL); SUPABASE_URL and
  SUPABASE_JWKS_URL through urllib. Local = the name `localhost`, a loopback IP (127.0.0.0/8,
  ::1) or a Unix-socket directory. Nothing is matched by substring.
- a non-local target that comes from backend/.env is NEUTRALIZED for the session: every
  SUPABASE_* value taken from the file is set to "" (load_settings keeps "" -> None), which is
  exactly the CI no-DB state; DB tests skip by their existing gates and a warning is printed.
- a non-local target set explicitly in the process environment ABORTS the session.
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
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def db_hosts(url: str, environ: Mapping[str, str]) -> tuple[list[str], str | None, bool]:
    """(hosts libpq would reach, user, uses a service file) for a PostgreSQL URL/conninfo."""
    try:
        from psycopg.conninfo import conninfo_to_dict
        params = conninfo_to_dict(url)
    except Exception:  # noqa: BLE001 -- unparsable: treat as unknown (= not local)
        return (["<unparsable>"], None, False)
    hosts = [h for value in (params.get("host"), params.get("hostaddr")) if value for h in str(value).split(",")]
    if not hosts:                                     # libpq falls back to the environment, then the socket
        hosts = [h for k in ("PGHOST", "PGHOSTADDR") if environ.get(k) for h in environ[k].split(",")]
    service = bool(params.get("service") or environ.get("PGSERVICE"))
    user = params.get("user")
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


def enforce(environ: MutableMapping[str, str] | None = None, dotenv_path: Path | None = None) -> Decision:
    """Apply the decision to `environ` (default os.environ). Raises RuntimeError on abort."""
    environ = os.environ if environ is None else environ
    decision = assess(environ, read_dotenv(dotenv_path or BACKEND_DIR / ".env"))
    if decision.action == "abort":
        raise RuntimeError("refusing to run tests against a non-local target:\n  - " + "\n  - ".join(decision.reasons))
    for key in decision.neutralize:
        environ[key] = ""                             # load_settings' setdefault keeps "" -> None
    return decision
