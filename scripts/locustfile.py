"""Measure end-to-end retrieval latency separately from HTTP latency."""

import os
import time
from uuid import uuid4

import gevent
from locust import HttpUser, constant, task
from requests.exceptions import RequestException

QUERIES = [
    "Transformer self-attention for long document understanding and translation.",
    "Dense passage retrieval with a dual encoder trained on hard negatives.",
    "Diffusion models for image generation with a learned denoising objective.",
    "Contrastive image and text pretraining for zero-shot classification.",
    "Reinforcement learning with a policy gradient and an experience buffer.",
    "Sparse and dense hybrid ranking for scientific literature discovery.",
    "Representations for paraphrase detection using sentence embeddings.",
    "Low-rank adaptation of pretrained language models for instruction tuning.",
]
REPEAT = os.environ.get("BENCH_REPEAT", "0") == "1"
POLL_INTERVAL = 0.25
JOB_TIMEOUT = 120


class Researcher(HttpUser):
    wait_time = constant(0)

    def on_start(self):
        self.query_index = 0

    def http_json(self, method, path, name, allowed_statuses, **kwargs):
        with self.client.request(
            method, path, name=name, catch_response=True, timeout=10, **kwargs
        ) as response:
            if response.status_code not in allowed_statuses:
                message = f"{name} returned HTTP {response.status_code}"
                response.failure(message)
                raise RuntimeError(message)
            try:
                return response.json()
            except ValueError as error:
                response.failure("Invalid JSON response")
                raise RuntimeError(f"{name} returned invalid JSON") from error

    @task
    def search(self):
        text = QUERIES[self.query_index % len(QUERIES)]
        self.query_index += 1
        if not REPEAT:
            text = f"{text} Query instance {uuid4()}."

        started = time.monotonic()
        result_bytes = 0
        failure = None
        cached = False
        try:
            job = self.http_json(
                "POST", "/jobs", "POST /jobs", {200, 202}, json={"text": text}
            )
            cached = job["cache_hit"]
            while job["status"] in {"pending", "processing"}:
                if time.monotonic() - started >= JOB_TIMEOUT:
                    raise TimeoutError("Job deadline exceeded")
                gevent.sleep(POLL_INTERVAL)
                job = self.http_json(
                    "GET", f"/jobs/{job['job_id']}", "GET /jobs/{id}", {200}
                )
            if job["status"] != "completed" or not job["results"]:
                raise RuntimeError("Job did not return any ranked papers")
            result_bytes = len(str(job["results"]).encode("utf-8"))
        except (KeyError, RequestException, RuntimeError, TimeoutError) as error:
            failure = error

        elapsed_ms = (time.monotonic() - started) * 1000
        self.environment.events.request.fire(
            request_type="JOB", name="end-to-end", response_time=elapsed_ms,
            response_length=result_bytes, exception=failure, context={},
        )
        if not failure and cached:
            self.environment.events.request.fire(
                request_type="CACHE", name="hit", response_time=elapsed_ms,
                response_length=result_bytes, exception=None, context={},
            )
