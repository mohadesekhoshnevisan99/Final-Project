"""Exercise a running search service using only the Python standard library."""

import argparse
import json
import math
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

DEFAULT_URL = "http://127.0.0.1:8000"
DEMO_QUERY = (
    "A transformer architecture replaces recurrent neural networks with "
    "multi-head self-attention for sequence transduction and translation."
)


def request_json(base_url, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(base_url.rstrip("/") + path, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def submit(base_url, text):
    return request_json(base_url, "/jobs", {"text": text})


def status_of(base_url, job_id):
    status, body = request_json(base_url, f"/jobs/{job_id}")
    require(status == 200, f"Status query returned HTTP {status}: {body}")
    return body


def wait_for_completion(base_url, job_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = status_of(base_url, job_id)
        if job["status"] == "completed":
            return job
        require(job["status"] != "failed", f"Job failed: {job}")
        time.sleep(0.25)
    raise TimeoutError(f"Job {job_id} did not finish in {timeout:g} seconds")


def check_results(results, expected_count):
    require(isinstance(results, list), "Results must be a list")
    require(len(results) == expected_count, f"Expected {expected_count} results")
    ids = {result["arxiv_id"] for result in results}
    require(len(ids) == len(results), "Results contain duplicate papers")
    previous_score = math.inf
    for result in results:
        require(result["title"] and result["authors"], "Paper metadata is incomplete")
        require(result["url"].startswith("https://arxiv.org/abs/"), "Invalid paper URL")
        score = result["score"]
        require(-1.000001 <= score <= 1.000001, f"Invalid cosine score: {score}")
        require(score <= previous_score, "Results are out of rank order")
        previous_score = score


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--text", default=DEMO_QUERY)
    parser.add_argument("--no-cache", action="store_true", help="Expect a miss on repeat.")
    args = parser.parse_args()

    status, health = request_json(args.url, "/healthz")
    require(status == 200 and health["papers"] > 0, f"Corpus unavailable: {health}")
    expected_count = min(10, health["papers"])
    status, _ = submit(args.url, "")
    require(status == 422, f"Empty input should return 422, got {status}")

    query = f"{args.text} Test reference {uuid4()}."
    started = time.monotonic()
    status, accepted = submit(args.url, query)
    require(status == 202 and accepted["job_id"], f"Fresh query was not accepted: {accepted}")
    completed = wait_for_completion(args.url, accepted["job_id"], args.timeout)
    cold_ms = round((time.monotonic() - started) * 1000, 2)
    check_results(completed["results"], expected_count)

    started = time.monotonic()
    if args.no_cache:
        status, repeated = submit(args.url, query)
        require(status == 202, "Repeated query should miss when cache is disabled")
        cached_ms = None
        wait_for_completion(args.url, repeated["job_id"], args.timeout)
    else:
        deadline = time.monotonic() + min(args.timeout, 10)
        status, repeated = submit(args.url, query)
        # The worker commits the result before writing its best-effort cache entry.
        while status == 202 and time.monotonic() < deadline:
            time.sleep(0.25)
            started = time.monotonic()
            status, repeated = submit(args.url, query)
        require(status == 200 and repeated["cache_hit"], "Repeated query never hit Redis")
        require(repeated["results"] == completed["results"], "Cached results changed")
        cached_ms = round((time.monotonic() - started) * 1000, 2)

    print(json.dumps({
        "papers": health["papers"],
        "job_id": accepted["job_id"],
        "attempts": completed["attempts"],
        "cold_job_ms": cold_ms,
        "cache_hit_ms": cached_ms,
        "top_results": completed["results"],
    }, indent=2))


if __name__ == "__main__":
    main()
