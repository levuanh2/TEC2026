"""The API must boot in an environment without the CV stack.

`backend/requirements.txt` does not install torch/torchvision/Pillow (they live
in `ml/requirements.txt`), so a small deployment — Render Free's 512 MB
instance, for example — runs the API without them. Before this, `service.py`
imported `PIL` and `ml.infer` (which imports torch) at module level, so the
whole process failed to start there. CV degrading to 503 is the designed
behaviour; the process dying is not.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_CV_MODULES = ("torch", "torchvision", "PIL", "PIL.Image", "ml.infer", "ml.model")


class _BlockCvImports:
    """Make the CV packages look absent, as they are on a CV-less install."""

    def find_module(self, name, path=None):  # pragma: no cover - legacy hook
        return None

    def find_spec(self, name, path=None, target=None):
        if name in _CV_MODULES or name.split(".")[0] in {"torch", "torchvision"}:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return None


@pytest.fixture
def without_cv():
    blocker = _BlockCvImports()
    saved = {name: sys.modules.pop(name, None) for name in (*_CV_MODULES, "service", "api", "main")}
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        for name in (*_CV_MODULES, "service", "api", "main"):
            sys.modules.pop(name, None)
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module


def test_service_imports_without_the_cv_stack(without_cv):
    service = importlib.import_module("service")
    assert service.Image is None and service.predict_with_model is None
    # The rest of the domain is intact: this is the module every write route uses.
    assert hasattr(service, "ActivityWriteService") and hasattr(service, "CarbonService")


def test_cv_service_is_simply_unavailable_rather_than_fatal(without_cv):
    main = importlib.import_module("main")
    assert main._build_cv_service() is None  # CV routes answer 503, app keeps running
    assert main.app is not None
