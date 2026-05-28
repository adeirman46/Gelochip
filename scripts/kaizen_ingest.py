"""
Build the three Kaizen ChromaDB knowledge collections from the project datasets.

Run from repo root with the venv:
    .venv/bin/python scripts/kaizen_ingest.py            # texts/abstracts/jsonl
    .venv/bin/python scripts/kaizen_ingest.py --pdfs     # also parse raw PDFs (slow)
"""
import argparse
import os
import sys

os.environ.setdefault("PDK_ROOT", os.path.expanduser("~/pdks"))
sys.path.insert(0, os.path.abspath("src"))

from gelochip.kaizen import collections, config  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdfs", action="store_true", help="also parse raw PDFs (slow)")
    args = ap.parse_args()

    print(f"ChromaDB → {config.CHROMA_DIR}")
    print(f"Embedding model → {config.EMBED_MODEL}\n")

    counts = collections.build_all(parse_pdfs=args.pdfs)
    print("\nIngested chunks per collection:")
    for name, n in counts.items():
        print(f"  {name:28s} {n:>6d}")
    print("\nLive counts:", collections.collection_counts())


if __name__ == "__main__":
    main()
