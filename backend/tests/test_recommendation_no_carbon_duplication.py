"""Architectural regression: the recommendation package must never grow its
own emissions math (brief M05 §B21). All carbon evidence must come from
calling back into `carbon.calculate_carbon` via a CarbonService-shaped
object — never a re-implemented formula or a copied constant.

Scans identifiers only (via `ast`), not docstrings/comments/string literals,
so this doesn't false-positive on prose that explains *why* (e.g. "gwp.ch4"
mentioned in an error message or a comment is fine; a variable or function
named after one of these methodology internals is not).
"""
from __future__ import annotations

import ast
from pathlib import Path

RECOMMENDATION_DIR = Path(__file__).resolve().parent.parent / "recommendation"

_FORBIDDEN_IDENTIFIERS = {"efc", "sfw", "sfp", "cfoa", "gwp", "ch4", "n2o", "ef1fr"}


def _identifiers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
        elif isinstance(node, ast.FunctionDef):
            names.add(node.name.lower())
    return names


def test_recommendation_package_never_computes_emissions_itself():
    offenders: list[str] = []
    for path in RECOMMENDATION_DIR.rglob("*.py"):
        hit = _identifiers(path) & _FORBIDDEN_IDENTIFIERS
        if hit:
            offenders.append(f"{path.name}: identifier(s) {sorted(hit)}")
    assert not offenders, (
        "recommendation/ must derive every number by calling the Carbon "
        "Engine, never by re-implementing its formulas: " + "; ".join(offenders)
    )


def test_recommendation_rules_only_import_carbon_error_types_not_methodology():
    """The only allowed import from `carbon` is the error hierarchy — never
    `methodology`/`factors` internals, which is where the real formulas live."""
    text = (RECOMMENDATION_DIR / "rules.py").read_text(encoding="utf-8")
    assert "from carbon import CarbonEngineError" in text
    assert "carbon.methodology" not in text
    assert "carbon.factors" not in text
    assert "calculate_carbon" not in text, (
        "rules.py must call a CarbonCalculator (service.CarbonService), "
        "never carbon.calculate_carbon directly — that would let a rule "
        "bypass the persist/repository layer and is a sign it's reaching "
        "for engine internals instead of the service boundary."
    )
