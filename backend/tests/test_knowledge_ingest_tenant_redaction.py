"""The operator CLI's plan summary must not print a tenant document's heading text.

Headings of a tenant document are tenant-private (a farm, a household, a plot). The summary prints
them as "(section i of n, heading withheld: tenant document)". Public documents are printed
exactly as before. Only the printout changes: the plan, chunk ids and hashes are identical for
both visibilities. No database, Storage or network: the autouse fixture refuses all three.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from knowledge.ingest import plan
from knowledge.models import DocumentSpec, SourceSpec
from scripts import ingest_knowledge as cli
from tests.fixtures.knowledge import HERE

ORG = "00000000-0000-4000-8000-000000000001"
PRIVATE = ("Hộ ông Nguyễn Văn An — thửa 3 (TEST FIXTURE)", "Ruộng nhà bà Trần Thị Bình (TEST FIXTURE)",
           "Ghi chú riêng của hợp tác xã Tân Phú (TEST FIXTURE)")
ARGS = ["--source-id", "test-fixture-src", "--source-title", "TEST FIXTURE source", "--source-owner", "Test publisher",
        "--source-type", "guideline", "--document-id", "tenant-doc", "--document-version", "v1",
        "--title", "TEST FIXTURE doc", "--language", "vi"]
TENANT = ["--visibility", "tenant", "--organization-id", ORG]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*_a, **_k):
        pytest.fail("the dry run tried to reach the network, a database or Storage")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr("psycopg.connect", refuse)
    monkeypatch.setattr("supabase.create_client", refuse)
    monkeypatch.setattr(cli, "ingest", refuse)


def _doc(tmp_path: Path) -> Path:
    body = (f"# {PRIVATE[0]}\n\nTưới ngập khô xen kẽ, theo dõi mực nước bằng ống quan sát.\n\n"
            f"## {PRIVATE[1]}\n\nGiữ nước 3-5 cm lúc trổ bông.\n\n"
            f"## {PRIVATE[2]}\n\nGhi lượng nước tưới của từng lần tưới.\n")
    path = tmp_path / "tenant.md"
    path.write_text(body, encoding="utf-8")
    return path


def _plan(path: Path, visibility: str):
    source = SourceSpec("test-fixture-src", "TEST FIXTURE source", "Test publisher", "guideline", None, visibility,
                        ORG if visibility == "tenant" else None)
    document = DocumentSpec("test-fixture-src", "tenant-doc", "v1", "TEST FIXTURE doc", "vi")
    return plan(data=path.read_bytes(), filename=path.name, source=source, document=document)


def _legacy_chunk_lines(p) -> list[str]:
    """The chunk lines exactly as the CLI printed them before this change."""
    return [f"  {c.ordinal:>4}  {c.chunk_id}  {c.tokens:>4} tok  p{c.page_from or '-'}-{c.page_to or '-'}  "
            f"{c.section_path or '(no section)'}" for c in p.chunks]


def test_public_output_is_exactly_as_before(capsys):
    for path in (HERE / "awd_guide.md", HERE / "straw_notes.txt"):
        assert cli.main(["--file", str(path), "--dry-run", *ARGS]) == 0
        out = capsys.readouterr().out.splitlines()
        p = _plan(path, "public")
        chunk_lines = [line for line in out if line.startswith("  ") and p.chunks and any(
            c.chunk_id in line for c in p.chunks)]
        assert chunk_lines == _legacy_chunk_lines(p)
        assert any(c.section_path for c in p.chunks) or path.suffix == ".txt"


def test_tenant_dry_run_prints_no_heading_text(capsys, tmp_path):
    path = _doc(tmp_path)
    assert cli.main(["--file", str(path), "--dry-run", *ARGS, *TENANT]) == 0
    out = capsys.readouterr().out
    for heading in PRIVATE:
        for fragment in (heading, heading.split(" (")[0], heading.split(" — ")[0]):
            assert fragment not in out, fragment
    assert "Nguyễn Văn An" not in out and "Trần Thị Bình" not in out and "Tân Phú" not in out


def test_tenant_labels_keep_the_structure_without_the_text(tmp_path):
    p = _plan(_doc(tmp_path), "tenant")
    sections = list(dict.fromkeys(c.section_path for c in p.chunks if c.section_path))
    assert len(sections) >= 2
    labels = cli.section_labels(p)
    assert [labels[s] for s in sections] == [
        f"(section {i} of {len(sections)}, heading withheld: tenant document)" for i in range(1, len(sections) + 1)]
    out = cli.summary(p, mode="dry-run")
    for c in p.chunks:                                     # every chunk still listed with its id
        assert c.chunk_id in out


def test_tenant_review_report_also_prints_no_heading(capsys, tmp_path):
    path = _doc(tmp_path)
    argv = ["--file", str(path), "--dry-run", "--integrity-review", "--as-of", "2026-11-09", *ARGS, *TENANT]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "== integrity review" in out
    assert not any(h.split(" (")[0] in out for h in PRIVATE)


def test_write_mode_summary_withholds_tenant_headings_too(tmp_path):
    class Result:
        outcome, status, source_status = "created", "review_required", "review_required"
        artifact_ref, artifact_created, notes = "knowledge-artifacts/" + "0" * 64 + "/tenant.md", True, ()

    out = cli.summary(_plan(_doc(tmp_path), "tenant"), mode="write", target="local", result=Result())
    assert not any(h.split(" (")[0] in out for h in PRIVATE)
    assert "heading withheld: tenant document" in out


def test_redaction_never_changes_the_plan(tmp_path):
    path = _doc(tmp_path)
    public, tenant = _plan(path, "public"), _plan(path, "tenant")
    assert [c.chunk_id for c in public.chunks] == [c.chunk_id for c in tenant.chunks]
    assert [c.content for c in public.chunks] == [c.content for c in tenant.chunks]
    assert [c.section_path for c in public.chunks] == [c.section_path for c in tenant.chunks]
    assert (public.file_sha256, public.normalized_sha256, public.chunker_version) == \
           (tenant.file_sha256, tenant.normalized_sha256, tenant.chunker_version)
    cli.summary(tenant, mode="dry-run")
    assert [c.section_path for c in tenant.chunks] == [c.section_path for c in public.chunks]   # not mutated
