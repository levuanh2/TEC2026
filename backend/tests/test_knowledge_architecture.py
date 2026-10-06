"""Import and write contracts of the V1.3-C ingestion foundation (docs/rag/RAG_V1_INGESTION.md).

AST-based, like test_rag_architecture.py:
- backend/knowledge is pure: stdlib + its own modules; only parsers/pdf.py may import pypdf;
  never a database/network/vendor SDK, vector store, embedding runtime or app layer;
- the operator adapter (infrastructure/knowledge_repo.py) only INSERTs and SELECTs and never
  names a status or approval column in SQL: ingestion cannot approve, update or delete;
- no API/app module imports the ingestion pipeline (no upload route).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
KNOWLEDGE = sorted((BACKEND / "knowledge").rglob("*.py"))
REPO = BACKEND / "infrastructure" / "knowledge_repo.py"
ISOLATION = BACKEND / "infrastructure" / "pdf_isolation.py"
CLI = BACKEND / "scripts" / "ingest_knowledge.py"

_STDLIB = {"__future__", "contextlib", "dataclasses", "datetime", "hashlib", "io", "json", "math", "re", "typing", "unicodedata",
           "collections", "knowledge"}
_PDF_ONLY = {"pypdf"}
_FORBIDDEN = {
    "openai", "anthropic", "google", "cohere", "mistralai", "ollama", "langchain", "langchain_core", "llama_index",
    "transformers", "litellm", "sentence_transformers", "onnxruntime", "tokenizers", "numpy", "torch",
    "pgvector", "chromadb", "pinecone", "qdrant_client", "weaviate", "faiss",
    "supabase", "postgrest", "psycopg", "psycopg2", "sqlalchemy", "httpx", "requests", "urllib", "socket",
    "fastapi", "infrastructure", "service", "api", "main", "schemas", "recommendation",
    "os", "pathlib", "subprocess", "shutil", "tempfile", "zipfile", "tarfile", "pickle",
}


def _roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_knowledge_package_has_the_approved_modules():
    names = {p.relative_to(BACKEND / "knowledge").as_posix() for p in KNOWLEDGE}
    assert names == {"__init__.py", "models.py", "normalize.py", "chunking.py", "ids.py", "ports.py", "ingest.py",
                     "parsers/__init__.py", "parsers/markdown.py", "parsers/text.py", "parsers/pdf.py"}


@pytest.mark.parametrize("path", KNOWLEDGE, ids=lambda p: p.relative_to(BACKEND).as_posix())
def test_knowledge_modules_are_pure(path):
    roots = _roots(path)
    allowed = _STDLIB | (_PDF_ONLY if path.name == "pdf.py" else set())
    assert not roots & _FORBIDDEN, f"{path.name}: forbidden {sorted(roots & _FORBIDDEN)}"
    assert roots <= allowed, f"{path.name}: unexpected {sorted(roots - allowed)}"


def _sql(path: Path) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            out.append("".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values))
    statements = []
    for text in out:
        lowered = text.strip().lower()
        if lowered.startswith(("insert ", "select ", "update ", "delete ", "with ", "alter ", "truncate ")):
            statements.append(lowered)
    return statements


def test_ingestion_adapter_only_inserts_and_reads_and_never_approves():
    statements = _sql(REPO)
    assert statements, "no SQL found"
    verbs = {s.split()[0] for s in statements}
    assert verbs <= {"insert", "select"}, verbs
    inserts = [s for s in statements if s.startswith("insert")]
    assert len(inserts) == 3
    for s in inserts:
        columns = s.split("(", 1)[1].split(")", 1)[0]
        assert not {"status", "approved_by", "approved_at", "review_note"} & {c.strip() for c in columns.split(",")}, s
    source = REPO.read_text(encoding="utf-8")
    assert "disable trigger" not in source.lower() and "session_replication_role" not in source


def test_no_app_layer_imports_the_ingestion_pipeline():
    production = [p for p in BACKEND.rglob("*.py")
                  if not {"tests", "scripts", "knowledge", ".venv", "venv"} & set(p.relative_to(BACKEND).parts)
                  and p not in (REPO, ISOLATION)]
    for path in production:
        roots = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module)
            elif isinstance(node, ast.Import):
                roots |= {a.name for a in node.names}
        assert not {r for r in roots if r == "knowledge" or r.startswith("knowledge.")
                    or r.endswith("knowledge_repo")}, path.relative_to(BACKEND)


def test_only_the_isolated_worker_imports_the_pdf_parser():
    """No production module parses PDFs in-process: the in-process parser is imported only by the
    worker side of infrastructure/pdf_isolation.py, and the CLI injects the isolated parser."""
    importers = set()
    for path in BACKEND.rglob("*.py"):
        if {"tests", ".venv", "venv"} & set(path.relative_to(BACKEND).parts):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (
                    node.module == "knowledge.parsers.pdf"
                    or (node.module == "knowledge.parsers" and any(a.name == "pdf" for a in node.names))):
                importers.add(path.relative_to(BACKEND).as_posix())
    assert importers == {"infrastructure/pdf_isolation.py"}, importers
    assert "pdf_parser=parse_pdf_isolated" in CLI.read_text(encoding="utf-8")
    source = ISOLATION.read_text(encoding="utf-8")
    assert "multiprocessing" not in source and "import pickle" not in source and "os.fork" not in source
    assert '"-I", "-B"' in source
