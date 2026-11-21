"""HTTP contract tests without a live database, queue or storage service."""

from contextlib import nullcontext
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from research_similarity import api

JOB_ID = UUID("12345678-0000-4000-8000-000000000001")
TEXT = "Self-attention for machine translation and sequence transduction."
RESULTS = [{
    "arxiv_id": "1706.03762",
    "title": "Attention Is All You Need",
    "authors": "Ashish Vaswani et al.",
    "url": "https://arxiv.org/abs/1706.03762",
    "score": 0.91,
}]


@pytest.fixture
def dependencies(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "ready_snapshot", lambda: {"paper_count": 12, "digest": "test-corpus"})
    monkeypatch.setattr(api, "cache_get", lambda key: None)
    monkeypatch.setattr(api, "object_store", SimpleNamespace(
        put=lambda key, text: calls.append(("store", key, text))
    ))

    def create_job(kind, key, cache_key):
        calls.append((kind, key, cache_key))
        return JOB_ID

    monkeypatch.setattr(api, "create_job", create_job)
    return calls


@pytest.mark.parametrize("payload", [
    {}, {"text": ""}, {"text": " \n\t "}, {"text": 25}, {"text": "q" * 12001},
])
def test_rejects_invalid_query(payload, dependencies):
    response = TestClient(api.app).post("/jobs", json=payload)
    assert response.status_code == 422
    assert dependencies == []


def test_rejects_oversized_http_body(dependencies):
    response = TestClient(api.app).post("/jobs", json={"text": "x" * 66000})
    assert response.status_code == 413
    assert dependencies == []


def test_new_query_is_queued(dependencies):
    text_with_extra_whitespace = " \t " + TEXT.replace(" ", " \n  ") + "\n"
    response = TestClient(api.app).post("/jobs", json={"text": text_with_extra_whitespace})
    assert response.status_code == 202
    body = response.json()
    assert body["job_id"] == str(JOB_ID)
    assert body["status"] == "pending"
    assert body["cache_hit"] is False
    assert response.headers["Location"] == f"/jobs/{JOB_ID}"
    stored, queued = dependencies
    assert stored == ("store", queued[1], TEXT)
    assert queued[0] == "query"
    assert queued[2]


def test_cache_hit_returns_results_without_storing_a_new_job(monkeypatch, dependencies):
    monkeypatch.setattr(api, "cache_get", lambda key: RESULTS)
    response = TestClient(api.app).post("/jobs", json={"text": TEXT})
    assert response.status_code == 200
    body = response.json()
    assert body["cache_hit"] is True
    assert body["status"] == "completed"
    assert body["results"] == RESULTS
    assert dependencies == []


def test_empty_corpus_returns_503(monkeypatch, dependencies):
    monkeypatch.setattr(api, "ready_snapshot", lambda: None)
    response = TestClient(api.app).post("/jobs", json={"text": TEXT})
    assert response.status_code == 503
    assert dependencies == []


def test_job_status_returns_persisted_results(monkeypatch):
    row = {"status": "completed", "result": RESULTS, "error": None, "attempts": 2}
    db = SimpleNamespace(execute=lambda sql, params: SimpleNamespace(fetchone=lambda: row))
    monkeypatch.setattr(api, "connect_db", lambda: nullcontext(db))
    response = TestClient(api.app).get(f"/jobs/{JOB_ID}")
    assert response.status_code == 200
    assert response.json() == {
        "job_id": str(JOB_ID), "status": "completed", "results": RESULTS,
        "cache_hit": False, "error": None, "attempts": 2,
    }


def test_unknown_job_returns_404(monkeypatch):
    db = SimpleNamespace(execute=lambda sql, params: SimpleNamespace(fetchone=lambda: None))
    monkeypatch.setattr(api, "connect_db", lambda: nullcontext(db))
    response = TestClient(api.app).get(f"/jobs/{JOB_ID}")
    assert response.status_code == 404
