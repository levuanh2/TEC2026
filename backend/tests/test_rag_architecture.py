"""Import contracts of the RAG core (docs/rag/RAG_V1_ARCHITECTURE.md §5).

AST-based, like test_recommendation_no_carbon_duplication.py: the RAG core may
depend only on pydantic, the stdlib, `carbon`'s scenario vocabulary/error type
and `recommendation.rules`; never on a vendor SDK, a vector store, a database
client or the app layers; and the Core V1 recommendation package must not
depend on RAG.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
RAG_DIR = BACKEND / "recommendation" / "rag"
RAG_MODULES = sorted(RAG_DIR.glob("*.py"))

_ALLOWED_ROOTS = {"__future__", "collections", "dataclasses", "datetime", "enum", "typing", "uuid",
                  "pydantic", "carbon", "recommendation"}
_ALLOWED_CARBON_NAMES = {"SCENARIOS", "CarbonEngineError"}
_FORBIDDEN_ROOTS = {
    # model providers / LLM frameworks
    "openai", "anthropic", "google", "vertexai", "cohere", "mistralai", "ollama", "langchain",
    "langchain_core", "llama_index", "transformers", "litellm",
    # vector stores / embeddings
    "pgvector", "chromadb", "pinecone", "qdrant_client", "weaviate", "faiss", "sentence_transformers",
    # database / network / web
    "supabase", "postgrest", "psycopg", "psycopg2", "sqlalchemy", "httpx", "requests", "fastapi",
    # app layers
    "infrastructure", "service", "api", "main", "schemas",
}


def _imports(path: Path) -> list[tuple[str, tuple[str, ...], int]]:
    """(absolute module, imported names, level) for each import statement."""
    out: list[tuple[str, tuple[str, ...], int]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            out.extend((alias.name, (), 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append((node.module or "", tuple(alias.name for alias in node.names), node.level))
    return out


def test_rag_package_exists_with_its_modules():
    names = {p.stem for p in RAG_MODULES}
    assert {"contracts", "models", "context", "citations", "grounding", "orchestrator", "errors",
            "what_if", "retrieval", "intents", "answers"} <= names


@pytest.mark.parametrize("path", RAG_MODULES, ids=lambda p: p.name)
def test_rag_modules_import_only_allowed_dependencies(path):
    for module, names, level in _imports(path):
        if level:
            # `..rules` is the only way up: RAG may reach the Core V1 rule
            # contract, nothing else outside its package.
            assert level == 1 or (level == 2 and module == "rules"), f"{path.name}: from {'.' * level}{module}"
            continue
        root = module.split(".")[0]
        assert root not in _FORBIDDEN_ROOTS, f"{path.name} imports forbidden {module}"
        assert root in _ALLOWED_ROOTS, f"{path.name} imports unexpected {module}"
        if root == "carbon":
            assert module == "carbon", f"{path.name}: carbon internals ({module}) hold formulas/factors"
            assert set(names) <= _ALLOWED_CARBON_NAMES, f"{path.name}: carbon {sorted(set(names) - _ALLOWED_CARBON_NAMES)}"
        if root == "recommendation":
            assert module == "recommendation.rules" and names == ("CarbonCalculator",), f"{path.name}: {module}"


@pytest.mark.parametrize("path", RAG_MODULES, ids=lambda p: p.name)
def test_rag_modules_hold_no_numeric_factor_constants(path):
    """A float literal in RAG code would be a copied factor/benchmark/GWP."""
    floats = [node.value for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
              if isinstance(node, ast.Constant) and isinstance(node.value, float)]
    assert not floats, f"{path.name} has float literals {floats}"


def test_core_recommendation_does_not_depend_on_rag():
    for path in (BACKEND / "recommendation").glob("*.py"):
        for module, names, level in _imports(path):
            assert "rag" not in module.split(".") and "rag" not in names, f"{path.name} imports RAG"


def test_app_layers_do_not_wire_rag_yet():
    """V1 is contracts only: no route, service or adapter uses the RAG core."""
    for path in [BACKEND / "api.py", BACKEND / "main.py", BACKEND / "service.py",
                 *sorted((BACKEND / "infrastructure").glob("*.py"))]:
        assert "recommendation.rag" not in path.read_text(encoding="utf-8"), path.name


@pytest.mark.parametrize("path", RAG_MODULES, ids=lambda p: p.name)
def test_each_rag_module_imports_alone_without_a_cycle(path):
    """A fresh interpreter per module: an import cycle that a warm
    `sys.modules` would hide fails here."""
    module = "recommendation.rag" if path.stem == "__init__" else f"recommendation.rag.{path.stem}"
    done = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=BACKEND,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
