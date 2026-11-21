"""Run a repeatable Locust worker and cache sweep on an indexed Compose project."""

import argparse
import csv
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from compare_runs import summarize
from smoke import DEFAULT_URL, request_json, require


REPO = Path(__file__).resolve().parents[1]


class Benchmark:
    def __init__(self, args):
        self.args = args
        self.output = args.output.resolve()
        self.env = os.environ.copy()

    def docker(self, *args, capture=True, timeout=120):
        completed = subprocess.run(
            ["docker", *args], cwd=REPO, env=self.env, check=True,
            encoding="utf-8", capture_output=capture, timeout=timeout,
        )
        return completed.stdout.strip() if capture else None

    def compose(self, *args, **kwargs):
        return self.docker("compose", "-p", self.args.project, *args, **kwargs)

    def configure(self, workers, cache):
        self.env["APP_CACHE_ENABLED"] = "true" if cache else "false"
        self.compose(
            "up", "-d", "--no-build", "--wait", "--scale", f"worker={workers}",
            "api", "worker", capture=False,
        )
        # Compose knows whether containers have started. Check the consumer's model-ready log too.
        ids = self.compose("ps", "--status", "running", "-q", "worker").splitlines()
        require(len(ids) == workers, f"Expected {workers} running workers, got {len(ids)}")
        deadline = time.monotonic() + 120
        for container in ids:
            started = self.docker("inspect", "--format", "{{.State.StartedAt}}", container)
            while True:
                logs = subprocess.run(
                    ["docker", "logs", "--since", started, container],
                    cwd=REPO, env=self.env, capture_output=True, encoding="utf-8", check=True,
                )
                if "event=worker_ready" in logs.stderr + logs.stdout:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Timed out waiting for {container[:12]} to load its model")
                time.sleep(1)

    def locust(self, name, seconds, repeated):
        volume = ("-v", f"{self.output}:/bench-output") if name else ()
        export = ("--csv", f"/bench-output/{name}") if name else ()
        self.compose(
            "run", "--rm", "--no-deps", "-T", "-e", f"BENCH_REPEAT={int(repeated)}",
            *volume, "test",
            "locust", "-f", "scripts/locustfile.py", "--host", "http://api:8000",
            "--headless", "-u", str(self.args.users), "-r", str(self.args.users),
            "-t", f"{seconds}s", "--stop-timeout", "30", "--exit-code-on-error", "0", "--only-summary",
            *export, capture=False, timeout=seconds + 120,
        )

    def record_context(self):
        status, health = request_json(self.args.url, "/healthz")
        require(status == 200 and health["papers"] > 0, f"Corpus unavailable: {health}")
        if self.args.expect_papers:
            require(health["papers"] == self.args.expect_papers, f"Unexpected corpus: {health}")
        config = json.loads(self.compose("config", "--format", "json"))
        config_env = config["services"]["worker"]["environment"]
        require(int(config_env["APP_WORKER_DELAY_SECONDS"]) == 0, "Turn off the fault-test delay first")
        db_info = self.compose(
            "exec", "-T", "db", "psql", "-U", "papers", "-d", "papers", "-Atqc",
            "SELECT digest FROM corpus_snapshot WHERE status = 'completed'",
        )
        require(len(db_info) == 64, "Missing corpus digest")
        cpus = self.compose("exec", "-T", "api", "cat", "/proc/cpuinfo")
        processor = next((s.split(":", 1)[1].strip() for s in cpus.splitlines() if s.startswith("model name")), "")
        engine = json.loads(self.docker(
            "info", "--format",
            '{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}},"os":{{json .OperatingSystem}},'
            '"architecture":{{json .Architecture}},"version":{{json .ServerVersion}}}',
        ))
        context = {
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "engine": engine,
            "processor": processor,
            "compose": self.compose("version", "--short"),
            "health": health,
            "snapshot_sha256": db_info,
            "model_cpu_threads_per_worker": int(config_env["APP_MODEL_THREADS"]),
            "object_store": config_env["APP_STORAGE_BACKEND"],
            "users": self.args.users,
            "spawn_rate_per_s": self.args.users,
            "duration_s": self.args.seconds,
            "warmup_s": self.args.warmup,
            "cache_comparison_workers": self.args.cache_workers,
            "client": "Locust container on the same Compose host and network",
        }
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / "run-context.json").write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")

    def run(self):
        self.record_context()
        original = self.env.get("APP_CACHE_ENABLED")
        original_config = json.loads(self.compose("config", "--format", "json"))
        original_cache = original_config["services"]["api"]["environment"]["APP_CACHE_ENABLED"] == "true"
        original_workers = len(self.compose("ps", "--status", "running", "-q", "worker").splitlines())
        require(original_workers > 0, "Start at least one worker before running the benchmark")
        cases = [(f"unique-w{workers}", workers, False, False) for workers in (1, 2, 4, 8)]
        cases.extend([
            ("repeated-cache-off", self.args.cache_workers, False, True),
            ("repeated-cache-on", self.args.cache_workers, True, True),
        ])
        rows = []
        try:
            for name, workers, cache, repeated in cases:
                print(f"\n{name}: {workers} workers, cache {'on' if cache else 'off'}", flush=True)
                self.configure(workers, cache)
                if self.args.warmup:
                    self.locust(None, self.args.warmup, repeated)
                self.locust(name, self.args.seconds, repeated)
                rows.append(summarize(self.output / f"{name}_stats.csv"))
                with (self.output / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
                print(rows[-1], flush=True)
        finally:
            self.configure(original_workers, original_cache)
            if original is None:
                self.env.pop("APP_CACHE_ENABLED", None)
            else:
                self.env["APP_CACHE_ENABLED"] = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="similar-papers")
    parser.add_argument("--url", default=DEFAULT_URL, help="Host URL for the Compose readiness check")
    parser.add_argument("--output", type=Path, default=REPO / "results" / "local-benchmark")
    parser.add_argument("--expect-papers", type=int)
    parser.add_argument("--users", type=int, default=12)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--cache-workers", type=int, default=4)
    args = parser.parse_args()
    if min(args.users, args.seconds, args.cache_workers) < 1 or args.warmup < 0:
        parser.error("users, seconds, and cache workers must be positive, and warmup cannot be negative")
    Benchmark(args).run()


if __name__ == "__main__":
    main()
