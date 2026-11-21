"""Exercise worker state transitions without PostgreSQL or a broker."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from research_similarity import worker
from research_similarity.ranking import Embedder


@pytest.fixture
def job(monkeypatch):
    row = {
        "id": uuid4(),
        "kind": "query",
        "status": "pending",
        "attempts": 0,
        "cache_key": "cache-key",
        "object_key": "query.txt",
    }
    events = []

    class FakeConnection:
        def __enter__(self):
            self.changes = {}
            return self

        def __exit__(self, *_exception):
            self.changes.clear()

        def execute(self, sql, parameters):
            if "pg_try_advisory_lock" in sql:
                return SimpleNamespace(fetchone=lambda: {"acquired": True})
            if "SELECT * FROM jobs" in sql:
                return SimpleNamespace(fetchone=row.copy)
            if "SET status = 'processing'" in sql:
                self.changes.update(status="processing", attempts=parameters[0])
            elif "SET status = 'completed'" in sql:
                self.changes.update(status="completed", result=parameters[0].obj)
            elif "SET status = 'pending'" in sql:
                self.changes.update(status="pending")
            elif "SET status = 'failed'" in sql:
                self.changes.update(status="failed", error=parameters[0])
            else:
                raise AssertionError(sql)

        def commit(self):
            row.update(self.changes)
            self.changes.clear()
            events.append("commit:" + row["status"])

        def rollback(self):
            self.changes.clear()

    def cache_set(_key, result):
        events.append(("cache", row["status"], result))

    monkeypatch.setattr(worker, "connect_db", FakeConnection)
    monkeypatch.setattr(worker, "cache_get", lambda _key: None)
    monkeypatch.setattr(worker, "cache_set", cache_set)
    monkeypatch.setattr(worker, "settings", SimpleNamespace(worker_delay_seconds=0))
    monkeypatch.setattr(worker, "time", SimpleNamespace(
        sleep=lambda _seconds: None, perf_counter=lambda: 0
    ))
    return row, events


def test_redelivery_commits_once_before_cache(job, monkeypatch):
    row, events = job
    row.update(status="processing", attempts=1)
    results = [{"arxiv_id": "1706.03762"}]
    monkeypatch.setattr(worker, "perform_job", lambda *_args: results)
    assert worker.process_job(row["id"], Embedder("smoke"))
    assert row["attempts"] == 2 and row["result"] == results
    assert worker.process_job(row["id"], Embedder("smoke"))
    assert events == ["commit:processing", "commit:completed", ("cache", "completed", results)]


def test_failed_job_is_requeued_twice_and_then_committed(job, monkeypatch):
    row, events = job

    def fail(*_args):
        raise RuntimeError("simulated worker error")

    monkeypatch.setattr(worker, "perform_job", fail)
    model = Embedder("smoke")
    assert [worker.process_job(row["id"], model) for _ in range(4)] == [False, False, True, True]
    assert row["attempts"] == 3 and row["status"] == "failed"
    assert events == [
        "commit:processing", "commit:pending",
        "commit:processing", "commit:pending",
        "commit:processing", "commit:failed",
    ]
