# Local execution evidence

The runs use one Docker Compose deployment on a Windows laptop with an Ubuntu WSL 2 engine. Times in `run-context.json` use UTC. The same 25,000-paper corpus and CPU MiniLM model are used in all six benchmark conditions.

| Evidence | What it records |
| --- | --- |
| `index.txt` | Paper count, snapshot SHA-256, batch progress, and total ingestion time |
| `health.json` | Live service readiness and indexed paper count |
| `semantic-smoke.json` | One retrieval for dense passage retrieval, ordered results, and a Redis hit on a repeat |
| `pytest.txt` | Automated test output, including a live pgvector comparison with NumPy |
| `summary.csv` | Locust completed-job rates, job failures, p50/p95 latencies, and observed cache hit rates |
| `run-context.json` | Hardware available to Docker, client placement, and workload settings |
| `*_stats.csv` | Final raw measures from the 1/2/4/8-worker and cache off/on runs |
| `*_stats_history.csv` | Interval snapshots from the measured runs |
| `*_failures.csv`, `*_exceptions.csv` | Locust failure and exception details, empty when none occur |
| `faults.json` | Controlled worker termination, broker restart, and Redis outage results |

Use the `JOB / end-to-end` row in the raw CSVs when verifying search performance. The HTTP submit/status rows count individual HTTP requests. Each cache hit also appears as a separate `CACHE / hit` row. The table in the project report uses `summary.csv`. Follow the local evaluation guide to reproduce the full run. [Local evaluation guide](../LOCAL-EVALUATION.md)
