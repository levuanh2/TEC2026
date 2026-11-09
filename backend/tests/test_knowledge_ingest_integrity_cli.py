"""`ingest_knowledge.py --dry-run --integrity-review --as-of`: the offline source-integrity review
aid (knowledge/integrity, PR #52) printed after the ingestion plan.

It is a report for a human expert. These tests pin that it never decides anything, never writes,
never calls a database, Storage, network or provider, fails closed on a bad registry, and does not
change the plain dry run. They do NOT show that dev3-01 is fixed: nothing here blocks retrieval or
changes a knowledge status. The poisoned/clean AWD texts are the benchmark fixtures themselves
(scripts.rag_llm_benchmark), so this file and the benchmark cannot drift apart.
"""

from __future__ import annotations

import ast
import copy
import json
import re
import socket
import sys
from pathlib import Path

import pytest
import scripts.rag_llm_benchmark as bench
from knowledge.ingest import plan
from knowledge.models import DocumentSpec, SourceSpec

from scripts import ingest_knowledge as cli
from tests.fixtures.knowledge import HERE

AS_OF = "2026-11-09"
ORG = "00000000-0000-4000-8000-000000000001"
ARGS = ["--source-id", "test-fixture-src", "--source-title", "TEST FIXTURE source", "--source-owner", "Test publisher",
        "--source-type", "guideline", "--document-id", "awd-guide", "--document-version", "v1",
        "--title", "TEST FIXTURE doc", "--language", "vi"]
REVIEW = ["--dry-run", "--integrity-review", "--as-of", AS_OF]
CLEAN = [bench.AWD_CHUNKS[0]["content"], bench.AWD_CHUNKS[1]["content"]]
POISON = bench.CHUNK_PRESETS["poisoned_claim"]["content"]


def _doc(tmp_path: Path, paragraphs: list[str], name: str = "doc.md") -> Path:
    """One section per paragraph, so each paragraph becomes its own chunk."""
    body = "\n\n".join(f"## Mục {i}\n\n{text}" for i, text in enumerate(paragraphs, 1))
    path = tmp_path / name
    path.write_text(f"# TEST FIXTURE\n\n{body}\n", encoding="utf-8")
    return path


def _plan(path: Path, visibility: str = "public", org: str | None = None):
    source = SourceSpec("test-fixture-src", "TEST FIXTURE source", "Test publisher", "guideline", None, visibility, org)
    document = DocumentSpec("test-fixture-src", "awd-guide", "v1", "TEST FIXTURE doc", "vi")
    return plan(data=path.read_bytes(), filename=path.name, source=source, document=document)


def _run(capsys, argv: list[str]) -> tuple[int, str, str]:
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def _section(out: str) -> str:
    marker = "== integrity review"
    assert marker in out
    return out[out.index(marker):]


def _chunk_of(p, text: str) -> str:
    (chunk,) = [c for c in p.chunks if text in c.content]
    return chunk.chunk_id


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Every test here: no socket, database, Storage, settings, provider or ingestion write."""
    def refuse(*_a, **_k):
        pytest.fail("the dry run tried to reach the network, a database, Storage or a provider")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr("psycopg.connect", refuse)
    monkeypatch.setattr("supabase.create_client", refuse)
    monkeypatch.setattr("infrastructure.config.load_settings", refuse)
    monkeypatch.setattr(cli, "ingest", refuse)


# ------------------------------------------------------------------ 1. the plain dry run is unchanged

def test_without_the_flag_the_dry_run_output_is_exactly_the_existing_summary(capsys):
    path = HERE / "awd_guide.md"
    code, out, err = _run(capsys, ["--file", str(path), "--dry-run", *ARGS])
    assert code == 0 and err == ""
    assert out == cli.summary(_plan(path), mode="dry-run") + "\n"
    for marker in ("integrity review", "content_correctness", "decision =", "provenance", "registry"):
        assert marker not in out


def test_with_the_flag_the_summary_is_unchanged_and_the_report_follows_it(capsys):
    path = HERE / "awd_guide.md"
    code, out, _ = _run(capsys, ["--file", str(path), *REVIEW, *ARGS])
    assert code == 0
    assert out.startswith(cli.summary(_plan(path), mode="dry-run") + "\n\n== integrity review")


# ------------------------------------------------------------------ 2. a report for the local fixture

def test_the_flag_prints_a_complete_report_for_the_local_fixture(capsys):
    from knowledge.integrity.claims import CLAIM_EXTRACTOR_VERSION
    from knowledge.integrity.review import REVIEW_VERSION

    registry = cli.load_reference_registry()
    code, out, _ = _run(capsys, ["--file", str(HERE / "awd_guide.md"), *REVIEW, *ARGS])
    report = _section(out)
    assert code == 0
    for expected in (f"review_version     {REVIEW_VERSION}", f"claim_extractor    {CLAIM_EXTRACTOR_VERSION}",
                     f"registry_version   {registry.registry_version}", f"registry_digest    {registry.digest}",
                     "registry_file      knowledge/integrity/reference_registry.json",
                     f"as_of              {AS_OF}", "claims             ", "findings           ",
                     "limitation         ", "result             "):
        assert expected in report
    assert report.rstrip("\n").splitlines()[-3:] == ["provenance = not_evaluated",
                                                     "content_correctness = not_assessed", "decision = none"]
    for e in registry.entries:
        assert f"reference          {e.reference_id}  verification {e.verification_status}" in report


def test_the_report_is_deterministic(capsys):
    argv = ["--file", str(HERE / "awd_guide.md"), *REVIEW, *ARGS]
    assert _run(capsys, argv)[1] == _run(capsys, argv)[1]


def test_the_evaluation_date_is_the_one_given(capsys):
    _, out, _ = _run(capsys, ["--file", str(HERE / "awd_guide.md"), "--dry-run", "--integrity-review",
                              "--as-of", "2031-01-02", *ARGS])
    assert "as_of              2031-01-02" in out


# ------------------------------------------------------------------ 3./4. poisoned vs clean AWD

def test_the_poisoned_awd_fixture_is_flagged_for_expert_review_on_its_own_chunk(capsys, tmp_path):
    path = _doc(tmp_path, [*CLEAN, POISON])
    p = _plan(path)
    poisoned, clean = _chunk_of(p, POISON), [_chunk_of(p, t) for t in CLEAN]
    code, out, _ = _run(capsys, ["--file", str(path), *REVIEW, *ARGS])
    report = _section(out)
    assert code == 0                                        # a finding never changes the dry-run exit code
    assert "findings           2 (needs_expert_review 2; reference_conflict 2)" in report
    assert report.count("reference_conflict  NEEDS EXPERT REVIEW") == 2
    assert report.count(f"  chunks           {poisoned}") == 2
    assert ("  reference        ref-ch4-awd-not-eliminated  (engine_config_pointer; independently verified: no)"
            in report)
    assert "  reference        ref-water-records-required  (project_policy; independently verified: no)" in report
    assert "assertion/ch4.rice.emission_eliminated" in report and "assertion/records.water.not_required" in report
    assert not any(c in report for c in clean)
    assert "2 finding(s) need expert review" in report and "decision = none" in report


def test_the_clean_awd_fixture_has_no_detected_reference_conflict(capsys, tmp_path):
    code, out, _ = _run(capsys, ["--file", str(_doc(tmp_path, CLEAN)), *REVIEW, *ARGS])
    report = _section(out)
    assert code == 0
    assert "reference_conflict" not in report and "NEEDS EXPERT REVIEW" not in report
    assert "needs_expert_review 0" in report
    assert "result             no detected conflicts" in report


# ------------------------------------------------------------------ 5. no findings is not an approval

def test_an_empty_review_is_labelled_no_detected_conflicts_and_never_approves(capsys, tmp_path):
    code, out, _ = _run(capsys, ["--file", str(_doc(tmp_path, CLEAN)), *REVIEW, *ARGS])
    report = _section(out)
    (result,) = [line for line in report.splitlines() if line.startswith("result ")]
    assert result.startswith("result             no detected conflicts (")
    assert "not safe, not verified, not approved" in result
    assert "approval           NOT approved -- review_required" in out
    assert "decision = none" in report and "content_correctness = not_assessed" in report
    for line in out.splitlines():                           # every mention of approval / safety is negated
        claims_trust = re.search(r"approv|\bsafe\b|\bverified\b", line, re.IGNORECASE)
        if claims_trust and not line.lstrip().startswith("reference "):
            assert "not" in line.lower(), line
    assert code == 0


# ------------------------------------------------------------------ 6. registry trust is never promoted

_UNVERIFIED = {
    "reference_id": "ref-test-unverified-records", "parameter": "records.water.not_required", "kind": "qualitative",
    "assertion_holds": False,
    "source": {"title": "TEST FIXTURE reference", "locator": "test", "document_version": "1",
               "url": "https://example.org/test.pdf", "artifact_sha256": None},
    "scope": "test only", "stage": None, "rationale": "test only",
    "verification": {"status": "unverified", "pointer": None, "evidence_ref": None, "verified_by": None, "note": "x"},
}


def _registry_file(tmp_path: Path, monkeypatch, data) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(cli, "REGISTRY_FILE", path)
    return path


def test_an_unverified_registry_entry_is_reported_as_unverified_never_as_independently_verified(
        capsys, tmp_path, monkeypatch):
    _registry_file(tmp_path, monkeypatch, {"schema": "kn-reference-registry-1", "registry_version": "test-1",
                                           "entries": [_UNVERIFIED]})
    code, out, _ = _run(capsys, ["--file", str(_doc(tmp_path, [POISON])), *REVIEW, *ARGS])
    report = _section(out)
    assert code == 0
    assert ("reference          ref-test-unverified-records  verification unverified  independently_verified no"
            in report)
    assert "  reference        ref-test-unverified-records  (unverified; independently verified: no)" in report
    assert "independently_verified yes" not in report and "independently verified: yes" not in report
    assert "unsupported_assertion" in report                # no entry for the CH4 statement: still surfaced


@pytest.mark.parametrize("mutate", [
    lambda e: e["verification"].update(status="independently_verified"),                     # no evidence at all
    lambda e: (e["verification"].update(status="independently_verified", evidence_ref="a" * 64, verified_by="x")),
    lambda e: e["verification"].update(status="synthetic_test_fixture"),
], ids=["claimed-verified-no-evidence", "claimed-verified-no-artifact-hash", "synthetic"])
def test_a_registry_claiming_more_trust_than_it_records_is_refused(capsys, tmp_path, monkeypatch, mutate):
    entry = copy.deepcopy(_UNVERIFIED)
    mutate(entry)
    _registry_file(tmp_path, monkeypatch, {"schema": "kn-reference-registry-1", "registry_version": "test-1",
                                           "entries": [entry]})
    code, out, err = _run(capsys, ["--file", str(_doc(tmp_path, [POISON])), *REVIEW, *ARGS])
    assert code == 1 and out == "" and "refused [registry_invalid]" in err


# ------------------------------------------------------------------ 7. provenance is not evaluated

def test_missing_provenance_evidence_is_reported_as_not_evaluated(capsys, tmp_path, monkeypatch):
    import knowledge.integrity.provenance as provenance

    monkeypatch.setattr(provenance, "evaluate_provenance",
                        lambda *a, **k: pytest.fail("provenance was evaluated without independent evidence"))
    argv = ["--file", str(_doc(tmp_path, CLEAN)), *REVIEW, *ARGS, "--authority", "official",
            "--official-url", "https://mae.gov.vn/van-ban/qd-1.pdf", "--license-basis", "official_publication"]
    code, out, _ = _run(capsys, argv)
    report = _section(out)
    assert code == 0 and "provenance = not_evaluated" in report
    (line,) = [x for x in report.splitlines() if x.startswith("provenance  ")]
    assert line.startswith("provenance         not_evaluated -- ") and "operator assertions" in line
    assert not re.search(r"provenance\s+(=\s*)?(verified|incomplete|mismatch|unverified)\b", report)
    assert "mae.gov.vn" not in report                       # the claimed origin is not echoed as a result


# ------------------------------------------------------------------ 8. a malformed registry fails closed

@pytest.mark.parametrize("data", [
    "{not json",
    json.dumps({"schema": "kn-reference-registry-0", "registry_version": "x", "entries": [_UNVERIFIED]}),
    json.dumps({"schema": "kn-reference-registry-1", "registry_version": "x", "entries": []}),
    json.dumps({"schema": "kn-reference-registry-1", "registry_version": "x", "entries": [_UNVERIFIED, _UNVERIFIED]}),
    json.dumps({"schema": "kn-reference-registry-1", "registry_version": "x",
                "entries": [dict(_UNVERIFIED, kind="quantity", parameter="water.awd.dry_down_depth",
                                 assertion_holds=None, value_min=15, value_max=15, unit="day")]}),
    json.dumps([]),
], ids=["not-json", "wrong-schema", "no-entries", "duplicate-id", "incompatible-unit", "not-an-object"])
def test_a_malformed_registry_is_refused_not_skipped(capsys, tmp_path, monkeypatch, data):
    _registry_file(tmp_path, monkeypatch, data)
    code, out, err = _run(capsys, ["--file", str(_doc(tmp_path, [POISON])), *REVIEW, *ARGS])
    assert code == 1 and out == ""                          # no partial report, and no plain summary either
    assert err.startswith("refused [registry_invalid]: registry.json: ")


@pytest.mark.parametrize("kind", ["missing", "not-utf8", "directory"])
def test_an_unreadable_registry_is_refused(capsys, tmp_path, monkeypatch, kind):
    path = tmp_path / "registry.json"
    if kind == "not-utf8":
        path.write_bytes(b"\xff\xfe\x00{")
    elif kind == "directory":
        path.mkdir()
    monkeypatch.setattr(cli, "REGISTRY_FILE", path)
    code, out, err = _run(capsys, ["--file", str(_doc(tmp_path, [POISON])), *REVIEW, *ARGS])
    assert code == 1 and out == "" and "refused [registry_invalid]" in err


def test_a_bad_registry_does_not_affect_the_plain_dry_run(capsys, tmp_path, monkeypatch):
    _registry_file(tmp_path, monkeypatch, "{not json")
    code, out, _ = _run(capsys, ["--file", str(HERE / "awd_guide.md"), "--dry-run", *ARGS])
    assert code == 0 and "chunks" in out


# ------------------------------------------------------------------ 9./10. usage errors (exit 2)

@pytest.mark.parametrize("value", ["2026-13-01", "2026-02-30", "09/11/2026", "20261109", "2026-W45-1", "2026-11-9",
                                   "", "today", "2026-11-09T00:00"])
def test_an_invalid_evaluation_date_is_a_usage_error(capsys, value):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--file", str(HERE / "awd_guide.md"), "--dry-run", "--integrity-review", "--as-of", value, *ARGS])
    assert exc.value.code == 2 and "--as-of" in capsys.readouterr().err


def test_the_evaluation_date_is_never_defaulted(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--file", str(HERE / "awd_guide.md"), "--dry-run", "--integrity-review", *ARGS])
    assert exc.value.code == 2 and "explicit --as-of" in capsys.readouterr().err


def test_as_of_without_the_review_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--file", str(HERE / "awd_guide.md"), "--dry-run", "--as-of", AS_OF, *ARGS])
    assert exc.value.code == 2


@pytest.mark.parametrize("target", ["local", "abcdefgh"])
def test_the_review_is_refused_in_write_mode_before_any_settings_or_connection(capsys, target):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--file", str(HERE / "awd_guide.md"), "--target", target, "--integrity-review",
                  "--as-of", AS_OF, *ARGS])
    assert exc.value.code == 2 and "only valid with --dry-run" in capsys.readouterr().err


# ------------------------------------------------------------------ 11. no database, Storage, network or provider

_PROVIDERS = {"openai", "anthropic", "google", "cohere", "mistralai", "ollama", "litellm", "httpx", "requests",
              "psycopg", "supabase", "storage3", "postgrest", "infrastructure", "rag", "service", "api"}


def test_the_review_path_imports_no_store_network_or_provider_module(capsys, tmp_path):
    before = set(sys.modules)
    code, _, _ = _run(capsys, ["--file", str(_doc(tmp_path, [*CLEAN, POISON])), *REVIEW, *ARGS])
    assert code == 0
    new = set(sys.modules) - before - {"infrastructure.pdf_isolation"}   # the existing isolated-PDF parser injection
    new_roots = {m.split(".")[0] for m in new}
    assert not new_roots & _PROVIDERS, sorted(new_roots & _PROVIDERS)


def test_the_review_functions_only_import_the_pure_integrity_package():
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    functions = {"load_reference_registry", "claim_sources", "integrity_report", "_excerpt", "_shown"}
    for node in [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in functions]:
        for inner in ast.walk(node):
            if isinstance(inner, ast.ImportFrom):
                assert inner.module.startswith("knowledge.integrity."), (node.name, inner.module)
            assert not isinstance(inner, ast.Import), node.name
            if isinstance(inner, ast.Name):
                assert inner.id not in {"ingest", "psycopg", "create_client", "load_settings"}, node.name


# ------------------------------------------------------------------ 12. no secrets or private passages

def test_no_secret_and_no_whole_chunk_is_printed(capsys, tmp_path, monkeypatch):
    secret = "sk-test-not-printed-0123456789"
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", secret)
    monkeypatch.setenv("SUPABASE_DB_URL", f"postgresql://postgres:{secret}@127.0.0.1:54322/postgres")
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    path = _doc(tmp_path, [*CLEAN, POISON])
    _, out, err = _run(capsys, ["--file", str(path), *REVIEW, *ARGS])
    assert secret not in out + err
    for chunk in _plan(path).chunks:
        assert chunk.content not in out
        for paragraph in (*CLEAN, POISON):
            assert paragraph not in out
    for line in _section(out).splitlines():
        excerpts = re.findall(r"'([^']*)'$", line) if line.startswith("  claim ") else []
        assert all(len(e) <= 80 for e in excerpts), line


def test_a_tenant_document_prints_no_excerpt_at_all(capsys, tmp_path):
    private = "Bón 1.000 kg/ha vôi cho thửa ruộng riêng của hộ (TEST FIXTURE)."
    path = _doc(tmp_path, [POISON, private])
    argv = ["--file", str(path), *REVIEW, *ARGS, "--visibility", "tenant", "--organization-id", ORG]
    code, out, _ = _run(capsys, argv)
    report = _section(out)
    assert code == 0 and report.count("NEEDS EXPERT REVIEW") == 2
    assert "(excerpt withheld: tenant document)" in report and "unresolved_claim" in report
    for fragment in ("không cần ghi mực nước", "không còn phát thải", "1.000 kg/ha", "thửa ruộng riêng"):
        assert fragment not in report, fragment


def test_a_long_span_is_cut_to_a_short_excerpt():
    from knowledge.integrity.claims import Claim

    long = Claim("cl-x", "d/x@1", "c1", 0, 300, "không cần " + "rất " * 70 + "ghi mực nước", "assertion", "extracted")
    shown = cli._excerpt(long, True)
    assert len(shown) <= cli._EXCERPT_CHARS + 2 and shown.endswith("…'") and long.text not in shown
    assert cli._excerpt(long, False) == "(excerpt withheld: tenant document)"


# ------------------------------------------------------------------ regressions from the agy read-only review

DEPTH_15 = "Rút mực nước xuống 15 cm dưới mặt ruộng rồi tưới lại (TEST FIXTURE)."
DEPTH_1_5 = "Rút mực nước xuống 1,5 cm dưới mặt ruộng rồi tưới lại (TEST FIXTURE)."


def test_a_wrong_number_is_only_caught_against_another_chunk_never_against_the_registry(capsys, tmp_path):
    """The production registry has no numeric entry: alone, a wrong depth is informational only."""
    _, alone, _ = _run(capsys, ["--file", str(_doc(tmp_path, [DEPTH_1_5], "alone.md")), *REVIEW, *ARGS])
    report = _section(alone)
    assert "findings           1 (needs_expert_review 0; unreferenced_claim 1)" in report
    assert "result             no detected conflicts (1 informational finding(s) above; " in report

    path = _doc(tmp_path, [DEPTH_15, DEPTH_1_5], "both.md")
    p = _plan(path)
    code, out, _ = _run(capsys, ["--file", str(path), *REVIEW, *ARGS])
    report = _section(out)
    assert code == 0 and report.count("claim_conflict  NEEDS EXPERT REVIEW") == 1
    assert f"  chunks           {_chunk_of(p, DEPTH_15)}, {_chunk_of(p, DEPTH_1_5)}" in report
    assert "water.awd.dry_down_depth: 15 cm vs 1.5 cm" in report
    assert report.count("unreferenced_claim  informational") == 2
    assert "1 finding(s) need expert review" in report


def test_a_tenant_document_withholds_values_from_quantity_conflicts(capsys, tmp_path):
    path = _doc(tmp_path, [DEPTH_15, DEPTH_1_5])
    _, out, _ = _run(capsys, ["--file", str(path), *REVIEW, *ARGS, "--visibility", "tenant", "--organization-id", ORG])
    report = _section(out)
    assert "claim_conflict  NEEDS EXPERT REVIEW" in report
    assert "water.awd.dry_down_depth: values withheld (tenant document)" in report
    for fragment in ("15 cm", "1.5 cm", "1,5 cm", "dưới mặt ruộng"):
        assert fragment not in report, fragment
