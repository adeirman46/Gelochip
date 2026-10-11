#!/usr/bin/env python
"""Export / import the AnoaChip knowledge store as a COMMITTABLE seed.

Everything the agent has learned — the seeded glayout rules, the canonical cell
patterns, and every error→fix lesson saved during runs — lives in the Postgres
(pgvector) knowledge store + MinIO object bucket. Those aren't in git, so a fresh
clone would start "dumb".

This script dumps the WHOLE store to `data/knowledge_seed/` (rows.jsonl.gz with the
embeddings baked in + blobs/ for the raw files). Commit that folder and anyone who
clones the repo can `--import` it to boot with the exact same knowledge — no
re-embedding, no model download, no re-crawling.

Usage:
    uv run python scripts/export_knowledge.py            # export DB  -> data/knowledge_seed/
    uv run python scripts/export_knowledge.py --import   # seed  -> DB (run after a clone)
    uv run python scripts/export_knowledge.py --stats     # how many rows are in the DB now
    uv run python scripts/export_knowledge.py --out DIR   # export to a custom directory

Then commit the seed:
    git add data/knowledge_seed && git commit -m "Update knowledge seed"

On a fresh clone the seed is imported automatically the first time the store starts;
`--import` just forces it (and is handy in CI / scripted setup).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# make `src/anoa_chip` importable whether run via uv or plain python
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "src" / "anoa_chip"))


def _human(n: int) -> str:
    return f"{n:,}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Export/import the AnoaChip knowledge store as a git seed.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--import", dest="do_import", action="store_true",
                   help="load the committed seed INTO the database (run after cloning)")
    g.add_argument("--stats", action="store_true", help="print how many rows the DB holds and exit")
    ap.add_argument("--out", metavar="DIR", default=None,
                    help="seed directory (default: data/knowledge_seed/)")
    args = ap.parse_args()

    try:
        from memory_store import get_memory, SEED_DIR
    except Exception as e:  # noqa: BLE001
        print(f"✗ could not import the knowledge store: {e}", file=sys.stderr)
        return 2

    seed_dir = Path(args.out) if args.out else Path(SEED_DIR)

    mem = get_memory()
    if not getattr(mem, "enabled", False):
        print("✗ knowledge store is not available (is Postgres up? check ANOA_DATABASE_URL "
              "and `docker compose up -d`).", file=sys.stderr)
        return 1

    if args.stats:
        try:
            rows = mem.list_items(limit=100000)
            print(f"knowledge rows in DB: {_human(len(rows))}")
            by: dict[str, int] = {}
            for r in rows:
                by[r.get("kind", "?")] = by.get(r.get("kind", "?"), 0) + 1
            for k, v in sorted(by.items(), key=lambda kv: -kv[1]):
                print(f"  {k:12} {_human(v)}")
        except Exception as e:  # noqa: BLE001
            print(f"✗ stats failed: {e}", file=sys.stderr)
            return 1
        return 0

    if args.do_import:
        print(f"→ importing knowledge seed from {seed_dir} …")
        n = mem.import_seed(seed_dir)
        print(f"✓ imported {_human(n)} knowledge row(s) into the database."
              if n else "! nothing imported (seed missing/empty or DB not ready).")
        return 0 if n else 1

    # default: EXPORT
    print(f"→ exporting the knowledge store to {seed_dir} …")
    n = mem.export_seed(seed_dir)
    if not n:
        print("! nothing exported (DB not ready or empty).", file=sys.stderr)
        return 1
    rows_gz = seed_dir / "rows.jsonl.gz"
    blobs = seed_dir / "blobs"
    n_blobs = len(list(blobs.glob("*"))) if blobs.is_dir() else 0
    print(f"✓ exported {_human(n)} row(s) → {rows_gz}")
    print(f"  blobs: {_human(n_blobs)} file(s) → {blobs}/")
    print("\nCommit it so cloners inherit the same knowledge:")
    print(f"  git add {seed_dir.relative_to(REPO_ROOT)} && git commit -m 'Update knowledge seed'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
