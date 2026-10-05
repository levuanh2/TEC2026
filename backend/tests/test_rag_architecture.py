"""Import contracts of the RAG core (docs/rag/RAG_V1_ARCHITECTURE.md §5).

AST-based, like test_recommendation_no_carbon_duplication.py: the RAG core may
depend only on pydantic, the stdlib, `carbon`'s scenario vocabulary/error type
and `recommendation.rules`; never on a vendor SDK, a vector store, a database
client, factor configuration or the app layers; and the Core V1
recommendation package must not depend on RAG.

Numbers are protected behaviourally, not by guessing what a literal means:
test_rag_facts.py / test_rag_orchestrator.py prove every authoritative value
comes from an injected Core V1 service and that generated numbers need a
FactRef.
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

_ALLOWED_ROOTS = {"__future__", "collections", "dataclasses", "datetime", "decimal", "enum", "math", "re", "typing", "unicodedata", "uuid",
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
    # configuration / file access (emission factors live in config/*.yaml)
    "yaml", "os", "pathlib", "io", "importlib", "config",
}


def _imports(path: Path | str) -> list[tuple[str, tuple[str, ...], int]]:
    """(absolute module, imported names, level) for each import statement of a
    file, or of a source snippet."""
    source = path.read_text(encoding="utf-8") if isinstance(path, Path) else path
    out: list[tuple[str, tuple[str, ...], int]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out.extend((alias.name, (), 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append((node.module or "", tuple(alias.name for alias in node.names), node.level))
    return out


def test_rag_package_exists_with_its_modules():
    names = {p.stem for p in RAG_MODULES}
    assert {"contracts", "models", "context", "citations", "grounding", "orchestrator", "errors",
            "what_if", "retrieval", "intents", "answers", "facts", "claims", "prose"} <= names


def _import_violation(module: str, names: tuple[str, ...], level: int) -> str | None:
    """Why one RAG import statement breaks the dependency contract, or None."""
    if level:
        # `..rules` is the only way up: RAG may reach the Core V1 rule
        # contract, nothing else outside its package.
        return None if level == 1 or (level == 2 and module == "rules") else f"from {'.' * level}{module}"
    root = module.split(".")[0]
    if root in _FORBIDDEN_ROOTS:
        return f"imports forbidden {module}"
    if root not in _ALLOWED_ROOTS:
        return f"imports unexpected {module}"
    if root == "carbon":
        if module != "carbon":
            return f"carbon internals ({module}) hold formulas/factors"
        if not names:  # `import carbon` exposes every name through the module namespace
            return "bare `import carbon`"
        if not set(names) <= _ALLOWED_CARBON_NAMES:
            return f"carbon {sorted(set(names) - _ALLOWED_CARBON_NAMES)}"
    if root == "recommendation" and not (module == "recommendation.rules" and names == ("CarbonCalculator",)):
        return module
    return None


def _wires_rag(module: str, names: tuple[str, ...]) -> bool:
    return "rag" in module.split(".") or "rag" in names


@pytest.mark.parametrize("path", RAG_MODULES, ids=lambda p: p.name)
def test_rag_modules_import_only_allowed_dependencies(path):
    for statement in _imports(path):
        violation = _import_violation(*statement)
        assert violation is None, f"{path.name}: {violation}"


@pytest.mark.parametrize("source", [
    "import carbon",
    "import carbon.engine",
    "from carbon import ParameterSet",
    "from carbon.engine import CarbonEngine",
    "import recommendation.rules",
    "from recommendation import service",
    "from ... import service",
    "import supabase",
])
def test_import_contract_rejects_evasive_forms(source):
    assert any(_import_violation(*statement) for statement in _imports(source)), source


@pytest.mark.parametrize("path", RAG_MODULES, ids=lambda p: p.name)
def test_rag_modules_never_load_factor_configuration_or_files(path):
    """Factors/GWP live in carbon/factors + config/*.yaml behind CarbonService.
    RAG reaches neither: no file access and no reference to that config."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    forbidden = calls & {"open", "exec", "eval", "__import__"}
    assert not forbidden, f"{path.name} calls {sorted(forbidden)}"
    strings = [node.value.lower() for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    for marker in ("emission_factors", ".yaml", "ef_config_path", "parameterset"):
        assert not any(marker in text for text in strings), f"{path.name} references {marker}"


def test_core_recommendation_does_not_depend_on_rag():
    for path in (BACKEND / "recommendation").glob("*.py"):
        for module, names, _level in _imports(path):
            assert not _wires_rag(module, names), f"{path.name} imports RAG"


def test_app_layers_do_not_wire_rag_yet():
    """V1 is contracts only: no route, service or adapter in the app layers uses
    the RAG core — neither by any import form nor by a dynamic module string."""
    for path in [BACKEND / "api.py", BACKEND / "main.py", BACKEND / "service.py",
                 *sorted((BACKEND / "infrastructure").glob("*.py"))]:
        assert not any(_wires_rag(module, names) for module, names, _level in _imports(path)), path.name
        assert "recommendation.rag" not in path.read_text(encoding="utf-8"), path.name


_NOT_PRODUCTION = {"tests", "tests_strict", "__pycache__", ".venv", "venv"}
PRODUCTION_MODULES = sorted(
    path for path in BACKEND.rglob("*.py")
    if not _NOT_PRODUCTION & set(path.relative_to(BACKEND).parts) and RAG_DIR not in path.parents
)
#: The generation path: a provider adapter implements `AnswerGenerator` over
#: `GenerationInput` and returns a generated-answer shape; wiring one means
#: constructing a `RagOrchestrator`.
_GENERATION_NAMES = {"AnswerGenerator", "GenerationInput", "RagOrchestrator", "GeneratedAnswer", "InformationalAnswer"}


def _generation_references(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            found |= {alias.name for alias in node.names} & _GENERATION_NAMES
            if (node.module or "").split(".")[-1] == "orchestrator" and "rag" in (node.module or "").split("."):
                found.add(node.module or "")
        elif isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names if alias.name.startswith("recommendation.rag.orchestrator")}
        elif isinstance(node, ast.Attribute) and node.attr in _GENERATION_NAMES:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in _GENERATION_NAMES:
            found.add(node.id)
    return found


def test_no_answer_generator_is_wired_until_d8_is_closed():
    """D8 — READ-tier semantic advice gate (REQUIRED BEFORE ANY REAL LLM).

    An INFORMATIONAL answer has no recommendation slot, but its free text can
    still phrase advice ("nên rút nước định kỳ"), and nothing in V1 detects
    that. So no production module may touch the GENERATION path — implement
    `AnswerGenerator`, build a `GenerationInput`, wire a `RagOrchestrator` or
    handle a generated answer — and the RAG core holds no concrete generator.
    Retrieval and scope adapters (V1.3, `rag_application.py`) are not affected.
    A real generator lands only together with a closed D8 strategy
    (docs/rag/RAG_V1_ARCHITECTURE.md §11) and a deliberate change of this
    test, never by silently plugging into READ generation."""
    assert PRODUCTION_MODULES and BACKEND / "api.py" in PRODUCTION_MODULES
    for path in PRODUCTION_MODULES:
        found = _generation_references(path.read_text(encoding="utf-8"))
        assert not found, f"{path}: generation path {sorted(found)} before D8"
    for path in RAG_MODULES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and not any(getattr(b, "id", None) == "Protocol" for b in node.bases):
                methods = {item.name for item in node.body if isinstance(item, ast.FunctionDef)}
                assert "generate" not in methods, f"{path.name}: concrete generator {node.name} before D8"


@pytest.mark.parametrize("source", [
    "from recommendation.rag import AnswerGenerator",
    "from recommendation.rag.contracts import AnswerGenerator as Port",
    "from recommendation.rag import GenerationInput",
    "from recommendation import rag; rag.RagOrchestrator(retriever=r, generator=g, what_if=w)",
    "import recommendation.rag.orchestrator",
    "from recommendation.rag.orchestrator import _parse",
    "from recommendation.rag import InformationalAnswer",
])
def test_d8_gate_detects_every_generation_reference(source):
    assert _generation_references(source), source


@pytest.mark.parametrize("source", [
    "from recommendation.rag import KnowledgeRetriever, SeasonScopeResolver, build_retrieval_query",
    "from recommendation.rag import RetrievalQuery, EvidenceChunk, assert_tenant_isolation",
    "from recommendation.rag.contracts import SeasonFactsSource",
])
def test_d8_gate_leaves_v1_3_retrieval_and_scope_adapters_free(source):
    assert not _generation_references(source), source


@pytest.mark.parametrize("source", [
    "from recommendation import rag",
    "import recommendation.rag",
    "from recommendation.rag import RagOrchestrator",
    "from recommendation.rag.orchestrator import RagOrchestrator",
    "from .recommendation import rag",
])
def test_rag_wiring_is_detected_in_every_import_form(source):
    assert any(_wires_rag(module, names) for module, names, _level in _imports(source)), source


@pytest.mark.parametrize("path", RAG_MODULES, ids=lambda p: p.name)
def test_each_rag_module_imports_alone_without_a_cycle(path):
    """A fresh interpreter per module: an import cycle that a warm
    `sys.modules` would hide fails here."""
    module = "recommendation.rag" if path.stem == "__init__" else f"recommendation.rag.{path.stem}"
    done = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=BACKEND,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
