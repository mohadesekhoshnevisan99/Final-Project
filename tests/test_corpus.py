import gzip
import hashlib
import json

from research_similarity.corpus import CATEGORIES, prepare, records


def test_prepare_selects_stable_papers_from_metadata(tmp_path):
    ids = [f"2501.{index:05d}" for index in range(15)]
    raw = [
        {
            "id": arxiv_id,
            "title": f"Demo title {arxiv_id}",
            "authors": "Example author",
            "abstract": "Example abstract",
            "categories": "cs.LG cs.CL",
        }
        for arxiv_id in ids
    ]
    raw += [dict(raw[0]), dict(raw[1], id="1300.0000", categories="cs.DS")]
    gzip_source = tmp_path / "source.json.gz"
    reversed_source = tmp_path / "reversed.json"
    output = tmp_path / "snapshot.jsonl"
    reversed_output = tmp_path / "reversed-snapshot.jsonl"
    with gzip.open(gzip_source, "wt", encoding="utf-8") as stream:
        stream.writelines(json.dumps(row) + "\n" for row in raw)
    reversed_source.write_text(
        "".join(json.dumps(row) + "\n" for row in reversed(raw)), encoding="utf-8"
    )
    prepare(gzip_source, output, limit=6)
    prepare(reversed_source, reversed_output, limit=6)

    expected = sorted(ids, key=lambda arxiv_id: hashlib.sha256(arxiv_id.encode()).digest())[:6]
    result = list(records(output))
    assert output.read_bytes() == reversed_output.read_bytes()
    assert [row["arxiv_id"] for row in result] == sorted(expected)
    assert all(set(row["categories"]) & CATEGORIES for row in result)
