"""Build the benchmark corpus from the pinned arXiv metadata split."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlparse
from urllib.request import urlopen


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from research_similarity.corpus import CATEGORIES, prepare, records


REVISION = "7576b7717c7a9b8b0f1f9113e3b9c7ea6166c5b6"
SOURCE_URL = (
    "https://huggingface.co/datasets/TheDima/arxiv-cs-2022-2026/resolve/"
    f"{REVISION}/test.jsonl"
)
SOURCE_SHA256 = "b879f8119b6d56f4ec22ea05eb977b5271152068090cb4171255ade9dd98d96d"
PAPERS = 25_000


def download(destination: Path) -> None:
    with urlopen(SOURCE_URL, timeout=90) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)


def normalize(source: Path, destination: Path) -> None:
    with source.open("rb") as original:
        digest = hashlib.file_digest(original, "sha256").hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError(f"Source checksum mismatch: {digest}")

    with destination.open("w", encoding="utf-8", newline="\n") as output:
        for record in records(source):
            if not CATEGORIES.intersection(record["categories"]):
                continue
            url = urlparse(record["id"])
            if url.hostname != "arxiv.org" or not url.path.startswith("/abs/"):
                raise ValueError(f"Unexpected paper identifier: {record['id']}")
            paper = {
                "arxiv_id": url.path.removeprefix("/abs/"),
                "title": record["title"],
                "authors": ", ".join(author["name"] for author in record["authors"]),
                "abstract": record["summary"],
                "categories": record["categories"],
            }
            output.write(json.dumps(paper, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Path to the pinned test.jsonl file")
    parser.add_argument("--output", type=Path, default=REPO / "data" / "corpus.jsonl.gz")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="arxiv-corpus-") as temp:
        directory = Path(temp)
        source = args.source or directory / "test.jsonl"
        if args.source is None:
            print("Downloading the pinned arXiv metadata split", flush=True)
            download(source)
        normalized = directory / "eligible.jsonl"
        normalize(source, normalized)
        canonical = directory / "corpus.jsonl"
        prepare(normalized, canonical, PAPERS)
        content = canonical.read_bytes()
        if content.count(b"\n") != PAPERS:
            raise ValueError(f"Expected {PAPERS:,} eligible papers")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.suffix == ".gz":
            content = gzip.compress(content, mtime=0)
        args.output.write_bytes(content)
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
