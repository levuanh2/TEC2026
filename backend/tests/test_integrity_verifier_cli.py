"""RAG V1.5 M7 E7.1: the verifier runner's key loading, offline signature audit and CLI, in-process (the
separate-process run is in test_rag_knowledge_m7_e7_1_portable_attestation.py, where coverage is not traced).
The database connection is a fake; keys are synthetic, generated per test, written only to pytest's tmp_path.
"""

from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from infrastructure import integrity_verifier as iv

ENV = ("KNOWLEDGE_VERIFIER_DB_URL", "KNOWLEDGE_AUDIT_DB_URL", "KNOWLEDGE_VERIFIER_KEY_FILE", "KNOWLEDGE_VERIFIER_KEY_ID")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def pem(key, path):
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return str(path)


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class Conn:
    def __init__(self, rows=()):
        self.rows, self.sql, self.committed = list(rows), [], False

    def execute(self, sql, params=()):
        self.sql.append(sql)
        return Cursor(self.rows)

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_load_key_needs_a_key_file_of_ed25519(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="no key of its own"):
        iv.load_key()
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(RuntimeError, match="must be Ed25519"):
        iv.load_key(pem(rsa_key, tmp_path / "rsa.pem"))
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("KNOWLEDGE_VERIFIER_KEY_FILE", pem(key, tmp_path / "v.pem"))
    assert iv.public_key_bytes(iv.load_key()) == iv.public_key_bytes(key)


def test_the_offline_audit_reverifies_every_stored_signature():
    key, rogue = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    text = '{"format":"kn-integrity-verification-1"}'
    public = iv.public_key_bytes(key)
    rows = [(1, text, key.sign(text.encode()), public, "active"),
            (2, text, rogue.sign(text.encode()), public, "active"),
            (3, text, key.sign(text.encode()), public, "revoked")]
    assert iv.audit(Conn(rows)) == [(2, "signature does not verify"), (3, "signed by a revoked key")]


def test_build_statement_accepts_a_json_text_result_and_refuses_another_pin():
    data = {"pin": {"extractor_code_digest": "0" * 64, "extractor_version": "x"}}
    with pytest.raises(iv.PinMismatch):
        iv.build_statement(Conn([(json.dumps(data),)]), "r", "k")


def test_the_cli_needs_its_own_login_and_key_id(monkeypatch, capsys):
    assert iv.main(["--report-id", "r"]) == 2
    assert iv.main(["--audit"]) == 2
    assert "KNOWLEDGE_AUDIT_DB_URL" in capsys.readouterr().err
    import psycopg
    monkeypatch.setattr(psycopg, "connect", lambda url: Conn())
    monkeypatch.setenv("KNOWLEDGE_VERIFIER_DB_URL", "postgresql://verifier@db.invalid/x")
    assert iv.main(["--report-id", "r"]) == 2                              # no key id
    with pytest.raises(SystemExit):
        iv.main([])                                                         # neither --report-id nor --audit


def test_the_cli_signs_and_submits_or_refuses_on_a_pin_mismatch(tmp_path, monkeypatch, capsys):
    import psycopg
    conn = Conn()
    monkeypatch.setattr(psycopg, "connect", lambda url: conn)
    monkeypatch.setenv("KNOWLEDGE_VERIFIER_DB_URL", "postgresql://verifier@db.invalid/x")
    monkeypatch.setenv("KNOWLEDGE_VERIFIER_KEY_ID", "test-fixture-cli")
    monkeypatch.setenv("KNOWLEDGE_VERIFIER_KEY_FILE", pem(Ed25519PrivateKey.generate(), tmp_path / "v.pem"))
    monkeypatch.setattr(iv, "verify", lambda *a: 41)
    assert iv.main(["--report-id", "r"]) == 0 and conn.committed
    assert json.loads(capsys.readouterr().out) == {"verification_id": 41}

    def mismatch(*a):
        raise iv.PinMismatch("TEST FIXTURE: another build")
    monkeypatch.setattr(iv, "verify", mismatch)
    assert iv.main(["--report-id", "r"]) == 3


def test_the_cli_audit_exit_code_reports_problems(monkeypatch, capsys):
    import psycopg
    key = Ed25519PrivateKey.generate()
    text = "{}"
    rows = [(1, text, key.sign(text.encode()), iv.public_key_bytes(key), "active")]
    monkeypatch.setattr(psycopg, "connect", lambda url: Conn(rows))
    monkeypatch.setenv("KNOWLEDGE_AUDIT_DB_URL", "postgresql://auditor@db.invalid/x")
    assert iv.main(["--audit"]) == 0 and json.loads(capsys.readouterr().out) == {"problems": []}
    rows[0] = (1, text, Ed25519PrivateKey.generate().sign(text.encode()), iv.public_key_bytes(key), "active")
    assert iv.main(["--audit"]) == 1
