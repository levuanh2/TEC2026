"""Monitoring signals of the season Q&A pilot (docs/rag/RAG_QA_PILOT_SAFEGUARDS.md §2-§3).

The log lines `scripts/ops/rag_qa_log_summary.py` alerts on must exist, carry the tier, and never
carry a question, a token or a user id; a client X-Request-ID cannot forge log fields.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rag_qa  # noqa: E402
from infrastructure.request_context import RequestIdMiddleware  # noqa: E402
from rag_qa import QuestionInput, RagQuestionService  # noqa: E402
from recommendation.rag import RagIntent  # noqa: E402
from tests.fixtures.rag_fakes import SEASON_ID  # noqa: E402
from tests.test_rag_qa import Carbon, Reader, gate  # noqa: E402
from tests.test_rag_qa_log_summary import summary_tool  # noqa: E402

QUESTION = "Vì sao phát thải vụ này cao?"


def answer(service, caplog):
    with caplog.at_level(logging.INFO, logger=rag_qa.logger.name):
        service.answer(reader=Reader(), crop_season_id=SEASON_ID, request_id="req-1",
                       question=QuestionInput(question=QUESTION, intent=RagIntent.EXPLAIN))
    return [r.getMessage() for r in caplog.records if r.name == rag_qa.logger.name]


def test_read_only_question_line_carries_the_tier_and_no_question(caplog):
    lines = answer(RagQuestionService(carbon_service=Carbon(), write_gate=gate(), action_tier_enabled=False), caplog)
    line = next(m for m in lines if m.startswith("rag_question "))
    assert "tier=read_only" in line and "llm_calls=0" in line and "request_id=req-1" in line
    assert QUESTION not in "\n".join(lines)
    assert not any("rag_alert" in m for m in lines)
    assert summary_tool.summarise(lines)["alerts"] == []


def test_llm_calls_on_a_read_only_service_raise_the_tripwire(monkeypatch, caplog):
    """Simulate the impossible: a model call counted on a READ-only service."""
    real = rag_qa.UsageMeter

    class Counted(real):
        def __init__(self):
            super().__init__()
            self.calls = 1
    monkeypatch.setattr(rag_qa, "UsageMeter", Counted)
    lines = answer(RagQuestionService(carbon_service=Carbon(), write_gate=gate(), action_tier_enabled=False), caplog)
    assert any(m.startswith("rag_alert llm_calls_in_read_only request_id=req-1") for m in lines)
    kinds = {a["alert"] for a in summary_tool.summarise(lines)["alerts"]}
    assert kinds == {"llm_calls_in_read_only", "rag_alert"}


def test_action_tier_start_up_writes_an_alert_line(monkeypatch, caplog):
    import infrastructure.llm_client as llm_client
    monkeypatch.setenv("RAG_QA_ACTION_TIER_ENABLED", "true")
    monkeypatch.setattr(llm_client, "load_llm_settings", lambda: None)
    monkeypatch.setattr(llm_client, "build_llm_client", lambda settings: None)
    with caplog.at_level(logging.INFO, logger=rag_qa.logger.name):
        rag_qa.build_question_service(carbon_service=Carbon(), write_gate=gate())
    lines = [r.getMessage() for r in caplog.records]
    assert "rag_alert action_tier_enabled provider_configured=False" in lines
    assert "action_tier_enabled" in {a["alert"] for a in summary_tool.summarise(lines)["alerts"]}


def test_read_only_start_up_writes_no_alert(monkeypatch, caplog):
    monkeypatch.delenv("RAG_QA_ACTION_TIER_ENABLED", raising=False)
    with caplog.at_level(logging.INFO, logger=rag_qa.logger.name):
        rag_qa.build_question_service(carbon_service=Carbon(), write_gate=gate())
    lines = [r.getMessage() for r in caplog.records]
    assert "rag_question_service tier=read_only provider=not_loaded" in lines
    assert summary_tool.summarise(lines)["alerts"] == []


def _id_app():
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/x")
    def x():
        return {}
    return TestClient(app)


@pytest.mark.parametrize("supplied", ["abc-123", "a.b_c-D", "x" * 64, "7f9c2ba4-e88f-4e1e-9f8a-2d0b1c3e4f56"])
def test_a_safe_client_request_id_is_kept(supplied):
    assert _id_app().get("/x", headers={"X-Request-ID": supplied}).headers["X-Request-ID"] == supplied


@pytest.mark.parametrize("supplied", ["a status=200 duration_ms=1", "x" * 65, "id;drop", "a=b", "rid\tllm_calls=0"])
def test_an_unsafe_client_request_id_is_replaced(supplied, caplog):
    with caplog.at_level(logging.INFO, logger="agricarbon.access"):
        echoed = _id_app().get("/x", headers={"X-Request-ID": supplied}).headers["X-Request-ID"]
    assert echoed != supplied and len(echoed) == 36
    access = [r.getMessage() for r in caplog.records if r.name == "agricarbon.access"]
    assert access and supplied not in access[0] and f"request_id={echoed} " in access[0]
