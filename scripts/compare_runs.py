"""Extract successful jobs/sec, p50, p95, failures and hit rate from Locust CSVs."""

import argparse
import csv
from pathlib import Path
import sys


def summarize(path):
    with path.open(newline="", encoding="utf-8-sig") as source:
        stats = {(row["Type"], row["Name"]): row for row in csv.DictReader(source)}
    job = stats.get(("JOB", "end-to-end"))
    if job is None or not int(job["Request Count"]):
        raise ValueError(f"No end-to-end job observations in {path}")
    total = int(job["Request Count"])
    failed = int(job["Failure Count"])
    hit = stats.get(("CACHE", "hit"), {})
    successes = total - failed
    return {
        "run": path.name.removesuffix("_stats.csv"),
        "job_observations": total,
        "job_failures": failed,
        "successful_jobs_per_s": round(
            float(job["Requests/s"]) - float(job["Failures/s"]), 2
        ),
        "p50_ms": job["50%"],
        "p95_ms": job["95%"],
        "cache_hit_pct": round(100 * int(hit.get("Request Count", 0)) / successes, 2)
        if successes else "",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_files", type=Path, nargs="+")
    args = parser.parse_args()
    rows = [summarize(path) for path in args.csv_files]
    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    main()
