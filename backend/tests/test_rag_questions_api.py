"""POST /v1/crop-seasons/{id}/questions — route contract with in-memory Core V1 stand-ins.

The real-stack counterpart (real JWTs, RLS, write gate) is test_rag_questions_route_db.py
and the route's entry in tests/route_auth_manifest.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
from rag_qa import RagQuestionService  # noqa: E402
from tests.fixtures.rag_fakes import SEASON_ID  # noqa: E402
from tests.test_rag_qa import GOOD_RECOMMEND, Carbon, Llm, Reader, gate  # noqa: E402

URL = f"/v1/crop-seasons/{SEASON_ID}/questions"
AUTH = {"Authorization": "Bearer t"}


def client(service=None, reader=None, configured=True):
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._read_repo] = lambda: reader or Reader()
    if configured:
        app.dependency_overrides[api._rag_question_service] = lambda: service or RagQuestionService(carbon_service=Carbon())
    return TestClient(app)


def test_requires_a_bearer_token():
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).post(URL, json={"question": "?", "intent": "explain"})
    assert response.status_code == 401 and response.json()["detail"]["error"]["code"] == "unauthenticated"


def test_off_unless_configured():
    response = client(configured=False).post(URL, json={"question": "?", "intent": "explain"}, headers=AUTH)
    assert response.status_code == 503 and response.json()["detail"]["error"]["code"] == "backend_not_configured"


def test_explain_answer_shape():
    body = client().post(URL, json={"question": "Phát thải và việc tưới nước của vụ thế nào?", "intent": "explain"},
                         headers=AUTH).json()
    assert body["status"] == "generated" and body["provenance"]["answer_source"] == "system_composed"
    assert body["citations"] == [] and body["provenance"]["persisted"] is False  # facts answer, no document
    cited = client().post(URL, json={"question": "Tài liệu nào nói về tưới nước AWD?", "intent": "evidence"},
                          headers=AUTH).json()
    assert cited["citations"][0]["chunk_id"] == "c1"
    assert {f["usage"] for f in body["trusted_facts"]} == {"informational_safe"}


@pytest.mark.parametrize("extra", [{"organization_id": "x"}, {"farm_id": "x"}, {"tenant": "x"},
                                   {"visibility": "public"}, {"capability": "action_producing"},
                                   {"persist": True}, {"mode": "preview"}, {"top_k": 50}])
def test_client_controlled_scope_or_authority_is_refused(extra):
    response = client().post(URL, json={"question": "?", "intent": "explain", **extra}, headers=AUTH)
    assert response.status_code == 422


@pytest.mark.parametrize("payload", [
    {"question": "", "intent": "explain"},
    {"question": "x" * 2001, "intent": "explain"},
    {"question": "?", "intent": "unknown"},
    {"question": "?", "intent": "what_if"},
    {"question": "?", "intent": "explain", "what_if_scenario": "awd"},
    {"question": "?", "intent": "what_if", "what_if_scenario": "fertilizer"},
])
def test_invalid_questions_are_422(payload):
    assert client().post(URL, json=payload, headers=AUTH).status_code == 422


def test_out_of_scope_season_is_normalized_404():
    response = client(reader=Reader(visible=False)).post(URL, json={"question": "?", "intent": "explain"},
                                                         headers=AUTH)
    assert response.status_code == 404 and response.json()["detail"]["error"]["code"] == "not_found"


def test_recommend_without_write_is_404_and_never_reaches_the_provider():
    llm = Llm(GOOD_RECOMMEND)
    service = RagQuestionService(carbon_service=Carbon(), llm_client=llm, write_gate=gate(False))
    response = client(service).post(URL, json={"question": "?", "intent": "recommend"}, headers=AUTH)
    assert response.status_code == 404 and llm.requests == []


def test_recommend_with_write_and_a_provider():
    service = RagQuestionService(carbon_service=Carbon(), llm_client=Llm(GOOD_RECOMMEND), write_gate=gate())
    body = client(service).post(URL, json={"question": "?", "intent": "recommend"}, headers=AUTH).json()
    assert body["status"] == "generated" and body["provenance"]["answer_source"] == "model_generated"
    assert body["recommendations"][0]["rule_code"]


def test_recommend_without_a_provider_is_503():
    service = RagQuestionService(carbon_service=Carbon(), write_gate=gate())
    response = client(service).post(URL, json={"question": "?", "intent": "recommend"}, headers=AUTH)
    assert response.status_code == 503 and response.json()["detail"]["error"]["code"] == "generation_unavailable"


def test_ungrounded_output_is_502_without_internal_detail():
    bad = {**GOOD_RECOMMEND, "evidence_refs": [{"source_id": "invented-src", "chunk_id": "zz"}]}
    service = RagQuestionService(carbon_service=Carbon(), llm_client=Llm(bad), write_gate=gate())
    response = client(service).post(URL, json={"question": "?", "intent": "recommend"}, headers=AUTH)
    assert response.status_code == 502 and "invented-src" not in response.text


def test_retrieval_failure_is_503():
    class Broken(Reader):
        def knowledge_matches(self, *args):
            raise RuntimeError("postgrest down")
    response = client(reader=Broken()).post(URL, json={"question": "?", "intent": "evidence"}, headers=AUTH)
    assert response.status_code == 503 and "postgrest" not in response.text
