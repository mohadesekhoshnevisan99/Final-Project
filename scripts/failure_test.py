"""Exercise crash recovery in a dedicated Docker Compose demo deployment."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from smoke import (
    DEFAULT_URL,
    DEMO_QUERY,
    check_results,
    request_json,
    require,
    status_of,
    submit,
    wait_for_completion,
)

REPO = Path(__file__).resolve().parents[1]
QUEUE = "paper-similarity-jobs"


def compose(*args):
    result = subprocess.run(
        ["docker", "compose", *args], cwd=REPO, check=True,
        text=True, capture_output=True, timeout=120,
    )
    return result.stdout


def start_test_job(url, scenario):
    query = f"{DEMO_QUERY} Failure case {scenario} {uuid4()}."
    status, body = submit(url, query)
    require(status == 202 and body["job_id"], f"Expected a fresh job: {body}")
    return body["job_id"]


def wait_for(check, description, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {description}")


def worker_crash(url, timeout):
    workers = compose("ps", "--status", "running", "-q", "worker").splitlines()
    require(len(workers) == 1, "Worker crash test requires exactly one running worker")
    job_id = start_test_job(url, "worker-crash")
    wait_for(lambda: status_of(url, job_id)["status"] == "processing",
             "a worker to claim the job", timeout)
    try:
        compose("kill", "-s", "SIGKILL", "worker")
        state_after_crash = status_of(url, job_id)["status"]
        require(state_after_crash == "processing", "Worker finished before the crash")
    finally:
        compose("start", "worker")
    job = wait_for_completion(url, job_id, timeout)
    require(job["attempts"] >= 2, f"Expected a second claim after the crash: {job}")
    require(job == status_of(url, job_id), "Recovered job returned inconsistent results")
    return job


def rabbitmq_restart(url, timeout):
    compose("stop", "worker")
    try:
        job_id = start_test_job(url, "rabbitmq-restart")
        # With the only consumer stopped, the confirmed message must wait in RabbitMQ.
        def broker_has_message():
            try:
                output = compose("exec", "-T", "rabbitmq", "rabbitmqctl", "-q",
                                 "list_queues", "name", "messages_ready")
            except subprocess.CalledProcessError:
                return False
            for row in output.splitlines():
                fields = row.split()
                if len(fields) == 2 and fields[0] == QUEUE:
                    return int(fields[1]) > 0
            return False

        wait_for(broker_has_message, "the pending message to reach RabbitMQ", timeout)
        # Prevent an outbox replay from making a lost broker message look durable.
        compose("stop", "dispatcher")
        compose("restart", "rabbitmq")
        wait_for_broker(timeout)
        wait_for(broker_has_message, "the ready message to survive the restart", timeout)
    finally:
        compose("start", "dispatcher", "worker")
    return wait_for_completion(url, job_id, timeout)


def wait_for_broker(timeout):
    def broker_responds():
        try:
            compose("exec", "-T", "rabbitmq", "rabbitmq-diagnostics", "-q", "check_port_connectivity")
            return True
        except subprocess.CalledProcessError:
            return False

    wait_for(broker_responds, "RabbitMQ to recover", timeout)


def redis_outage(url, timeout):
    compose("stop", "redis")
    try:
        job_id = start_test_job(url, "redis-outage")
        job = wait_for_completion(url, job_id, timeout)
        require(not job["cache_hit"], "Job unexpectedly used the stopped cache")
        return job
    finally:
        compose("start", "redis")


def main():
    scenarios = {"worker": worker_crash, "rabbitmq": rabbitmq_restart, "redis": redis_outage}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=(*scenarios, "all"))
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()

    status, health = request_json(args.url, "/healthz")
    require(status == 200 and health["papers"] > 0, f"Corpus unavailable: {health}")
    selected = scenarios if args.scenario == "all" else {args.scenario: scenarios[args.scenario]}
    evidence = []
    for label, run in selected.items():
        job = run(args.url, args.timeout)
        check_results(job["results"], min(health["papers"], 10))
        evidence.append({
            "scenario": label, "job_id": job["job_id"], "attempts": job["attempts"],
            "status": job["status"], "results": len(job["results"]),
        })
        print(f"{label} recovery passed (attempts={job['attempts']})", file=sys.stderr)
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
