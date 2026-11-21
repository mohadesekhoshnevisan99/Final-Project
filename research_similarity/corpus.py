"""Prepare a reproducible arXiv snapshot and enqueue its embedding batches."""

import argparse
import gzip
import hashlib
import heapq
import json
from pathlib import Path
import re
import time
from uuid import NAMESPACE_URL, uuid5

CATEGORIES = {"cs.LG", "cs.CL", "cs.IR"}
ARXIV_ID = re.compile(r"(?:\d{4}\.\d{4,5}|[a-zA-Z][a-zA-Z0-9.-]*/\d{7})\Z")


def records(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{line_number}: invalid JSON") from error


def clean_text(value) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def paper_record(row: object) -> dict | None:
    if not isinstance(row, dict):
        return None
    arxiv_id = clean_text(row.get("arxiv_id") or row.get("id"))
    categories = row.get("categories", [])
    if isinstance(categories, str):
        categories = categories.split()
    if not isinstance(categories, list):
        return None
    category_set = {value for value in categories if isinstance(value, str)}
    if not ARXIV_ID.fullmatch(arxiv_id) or not CATEGORIES.intersection(category_set):
        return None
    paper = {
        "arxiv_id": arxiv_id,
        "title": clean_text(row.get("title")),
        "authors": clean_text(row.get("authors")),
        "abstract": clean_text(row.get("abstract")),
        "categories": sorted(category_set),
    }
    if not all(paper[key] for key in ("title", "authors", "abstract")):
        return None
    return paper


def snapshot_text(papers: list[dict]) -> str:
    return "".join(
        json.dumps(paper, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for paper in sorted(papers, key=lambda paper: paper["arxiv_id"])
    )


def prepare(source: Path, output: Path, limit: int) -> None:
    if source.resolve() == output.resolve():
        raise ValueError("Choose an output path different from the metadata source")
    # Keep the papers with the smallest stable ID digests in bounded memory.
    selected: dict[str, dict] = {}
    heap: list[tuple[int, str]] = []
    for row in records(source):
        paper = paper_record(row)
        if paper is None:
            continue
        arxiv_id = paper["arxiv_id"]
        if arxiv_id in selected:
            # Resolve duplicate metadata deterministically if a source contains revisions.
            selected[arxiv_id] = min(
                selected[arxiv_id], paper, key=lambda value: json.dumps(value, sort_keys=True)
            )
            continue
        rank = -int.from_bytes(hashlib.sha256(arxiv_id.encode()).digest(), "big")
        entry = (rank, arxiv_id)
        if len(heap) == limit:
            if entry <= heap[0]:
                continue
            _, removed = heapq.heapreplace(heap, entry)
            del selected[removed]
        else:
            heapq.heappush(heap, entry)
        selected[arxiv_id] = paper
    if not selected:
        raise ValueError("No matching arXiv metadata records found")

    output.parent.mkdir(parents=True, exist_ok=True)
    content = snapshot_text(list(selected.values())).encode("utf-8")
    output.write_bytes(content)
    print(f"{len(selected)} papers, SHA-256 {hashlib.sha256(content).hexdigest()}, {output}")


def index(path: Path, batch_size: int, timeout: float, retry_failed: bool = False):
    from .broker import create_job
    from .common import connect_db, object_store, settings

    papers = [paper_record(row) for row in records(path)]
    if not papers or any(paper is None for paper in papers):
        raise ValueError("The index input must contain valid papers in the prepared JSONL format")
    if len({paper["arxiv_id"] for paper in papers}) != len(papers):
        raise ValueError("The snapshot contains duplicate arXiv IDs")
    papers.sort(key=lambda paper: paper["arxiv_id"])
    content = snapshot_text(papers)
    digest = hashlib.sha256(content.encode()).hexdigest()
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO corpus_snapshot (digest, model_mode, paper_count, batch_size, status)
            VALUES (%s, %s, %s, %s, 'pending')
            ON CONFLICT (singleton) DO NOTHING
            """,
            (digest, settings.model_mode, len(papers), batch_size),
        )
        snapshot = conn.execute("SELECT * FROM corpus_snapshot WHERE singleton").fetchone()
    if (snapshot["digest"], snapshot["model_mode"]) != (digest, settings.model_mode):
        raise ValueError("This database holds another corpus or model. Use a fresh Compose project.")
    if snapshot["status"] == "completed":
        print(f"Already indexed {len(papers)} papers, SHA-256 {digest}", flush=True)
        return

    # An interrupted index uses the original batch boundaries and the same job IDs.
    batch_size = snapshot["batch_size"]
    prefix = f"corpora/{digest}"
    object_store.put(f"{prefix}/snapshot.jsonl", content)
    job_ids = []
    for start in range(0, len(papers), batch_size):
        key = f"{prefix}/batch-{start:06d}.json"
        job_id = uuid5(NAMESPACE_URL, key)
        object_store.put(key, json.dumps(papers[start:start + batch_size], ensure_ascii=False))
        create_job("index", key, job_id=job_id)
        job_ids.append(job_id)

    if retry_failed:
        with connect_db() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'pending', attempts = 0, error = NULL, published_at = NULL,
                    started_at = NULL, completed_at = NULL
                WHERE id = ANY(%s) AND status = 'failed'
                """,
                (job_ids,),
            )
    print(f"Waiting for {len(job_ids)} batches for {len(papers)} papers, SHA-256 {digest}", flush=True)
    deadline = time.monotonic() + timeout
    previous_completed = -1
    while time.monotonic() < deadline:
        with connect_db() as conn:
            states = {
                row["status"]: row["n"]
                for row in conn.execute(
                    "SELECT status, count(*) AS n FROM jobs WHERE id = ANY(%s) GROUP BY status",
                    (job_ids,),
                )
            }
            if states.get("failed"):
                raise RuntimeError("Index batch failed. Check worker logs and rerun index with --retry-failed.")
            completed = states.get("completed", 0)
            if completed == len(job_ids):
                count = conn.execute("SELECT count(*) AS n FROM papers").fetchone()["n"]
                if count != len(papers):
                    raise RuntimeError(f"Expected {len(papers)} papers in PostgreSQL, found {count}")
                conn.execute("UPDATE corpus_snapshot SET status = 'completed' WHERE singleton")
            elif completed != previous_completed:
                print(f"{completed}/{len(job_ids)} batches completed", flush=True)
                previous_completed = completed
        if completed == len(job_ids):
            print(f"Indexed {count} papers, SHA-256 {digest}", flush=True)
            return
        time.sleep(2)
    raise RuntimeError("Index wait timed out. Rerun the same command to resume waiting.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_cmd = commands.add_parser("prepare", help="filter a downloaded arXiv metadata snapshot")
    prepare_cmd.add_argument("source", type=Path)
    prepare_cmd.add_argument("--output", type=Path, default=Path("data/corpus.jsonl"))
    prepare_cmd.add_argument("--limit", type=int, default=25000)
    index_cmd = commands.add_parser("index", help="publish a fixed snapshot to the workers and wait")
    index_cmd.add_argument("snapshot", type=Path)
    index_cmd.add_argument("--batch-size", type=int, default=32)
    index_cmd.add_argument("--timeout", type=float, default=3600)
    index_cmd.add_argument("--retry-failed", action="store_true", help="reset failed index batches")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            if args.limit < 1:
                parser.error("--limit must be at least 1")
            prepare(args.source, args.output, args.limit)
        else:
            if not 1 <= args.batch_size <= 128 or not args.timeout > 0:
                parser.error("--batch-size must be 1 to 128 and --timeout must be positive")
            index(args.snapshot, args.batch_size, args.timeout, args.retry_failed)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
