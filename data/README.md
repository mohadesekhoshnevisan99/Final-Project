# Corpus inputs

`demo.jsonl` contains 15 real arXiv paper IDs and bibliographic records. The short summaries were written for this project. Paper URLs resolve to the original arXiv records.

## Benchmark snapshot

`corpus.jsonl.gz` contains 25,000 unique arXiv papers with their titles, authors, categories, and abstracts. The source is the test split of a computer science metadata snapshot collected through the arXiv Atom API. The source card describes a random split, seed 42, of papers published between January 2022 and July 2026. The service uses the snapshot as a retrieval corpus with a pretrained encoder. arXiv releases descriptive metadata, including abstracts, under CC0 1.0. [Pinned source snapshot](https://huggingface.co/datasets/TheDima/arxiv-cs-2022-2026/tree/7576b7717c7a9b8b0f1f9113e3b9c7ea6166c5b6), [arXiv metadata terms](https://info.arxiv.org/help/api/tou.html)

The preparation script verifies the source's SHA-256, keeps records with at least one of `cs.LG`, `cs.CL`, or `cs.IR`, selects the 25,000 IDs with the smallest SHA-256 hashes, and sorts the output by arXiv ID. Among the selected papers, 17,814 have `cs.LG`, 8,479 have `cs.CL`, and 1,575 have `cs.IR`. Categories can overlap.

| File | SHA-256 |
| --- | --- |
| Source `test.jsonl` | `b879f8119b6d56f4ec22ea05eb977b5271152068090cb4171255ade9dd98d96d` |
| Canonical corpus before compression | `a2b1049229ab37a247d65620983f477ba73b944a9cd2f98933f5c84b53c19788` |

From the repository root, rebuild the benchmark snapshot if needed. The pinned source download is 194 MB. Pass `--source PATH` to reuse a downloaded source.

```sh
python scripts/prepare_local_corpus.py
```

## Other arXiv snapshots

To construct another corpus from the official arXiv metadata snapshot, download the JSON Lines file and run the following from the repository root. [Official snapshot on Kaggle](https://www.kaggle.com/datasets/Cornell-University/arxiv) · [arXiv bulk data guide](https://info.arxiv.org/help/bulk_data.html)

```sh
python -m research_similarity.corpus prepare /path/to/arxiv-metadata-oai-snapshot.json --output data/corpus.jsonl --limit 25000
```

The importer accepts JSONL or gzip-compressed JSONL. Use a fresh deployment when changing snapshots and retain the source release date and corpus digest with the experiment. [Deployment guide](../docs/DEPLOYMENT.md)
