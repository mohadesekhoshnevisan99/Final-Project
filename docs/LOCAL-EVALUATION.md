# Local evaluation

Use the same Compose deployment, indexed corpus, and MiniLM model for the entire experiment. The Locust client runs in an ephemeral container on the same host. Its elapsed time includes the HTTP request and up to 250 ms of interval-based completion polling.

## Worker scaling and Redis

From the repository root, start the project, index the corpus, then build the test image. Use the same Compose project name for these steps and the experiment. A new Compose project has separate storage volumes.

```powershell
docker compose -p similar-papers up -d --build --wait
docker compose -p similar-papers run --rm tools python -m research_similarity.corpus index data/corpus.jsonl.gz --timeout 3600
docker compose -p similar-papers build test
docker compose -p similar-papers run --rm test
python scripts/smoke.py
python scripts/bench_local.py --project similar-papers --expect-papers 25000
```

The sweep runs 12 closed-loop Locust users with a one-second ramp, eight-second warm-up, and 30-second timed run per configuration. It starts 1, 2, 4, and 8 workers with the Redis cache disabled and sends unique queries based on the same eight research topics. It then compares repeated queries with the cache disabled and enabled at four workers. All 12 users replay the same eight query texts in the repeated workload. The cache-on warm-up populates their Redis keys before the measured run starts. The script waits for each worker to load its encoder and restores the starting worker count and cache setting afterward. [Locust headless runs](https://docs.locust.io/en/stable/running-without-web-ui.html)

The default destination is `results/local-benchmark`. `run-context.json` records the available Docker CPUs and memory, model, dataset checksum, and load parameters. `summary.csv` contains one row per configuration. The Locust `JOB / end-to-end` row measures one complete search and the `CACHE / hit` row counts results returned directly by the API's cache. The summary subtracts the overall failure rate from the overall job rate. A seed query to verify the UI may run before or after this experiment. Leave the experimental deployment alone while jobs are measured.

## Recovery checks

Run these checks separately from timing. The local worker starts each job, records its attempt, and sleeps briefly so the test can terminate it while it holds the delivery. The script also confirms a queued message survives a broker restart and verifies query completion with Redis stopped. On a project whose host port differs from the default, pass `--url` to both Python test scripts.

```powershell
$env:COMPOSE_PROJECT_NAME = 'similar-papers'
$env:APP_WORKER_DELAY_SECONDS = '15'
docker compose up -d --no-build --wait --scale worker=1
try {
    python scripts/failure_test.py all
} finally {
    Remove-Item Env:APP_WORKER_DELAY_SECONDS
    docker compose up -d --no-build --wait --scale worker=1
}
```

Expect completed jobs with 10 ordered results. Worker termination requires at least two attempts. For the broker restart, the dispatcher pauses until the test checks that the already-published message is still in the restarted broker. Redis restart clears the unpersisted cache. Use `docker compose logs worker dispatcher api` to trace job IDs when investigating failures.
