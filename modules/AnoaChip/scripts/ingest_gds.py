#!/usr/bin/env python3
"""Ingest every GDSII already produced into the durable store (Postgres row + MinIO blob).

"Don't forget all the GDS that were made — put them into postgres/object storage." This
sweeps the workspace for final layouts and stores each as a recallable ``kind='gds'`` item
(blob → MinIO, row + embedding → Postgres), de-duplicated by content hash so re-running is
idempotent. Run-intermediate GDS under ``chip/runs/.../NN-step/`` are skipped — only the
final per-design GDS (and any IP-library / Chip-Studio GDS) are kept.

    uv run python scripts/ingest_gds.py            # ingest everything found
    uv run python scripts/ingest_gds.py --dry-run  # list what WOULD be ingested
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "anoa_chip"))
from memory_store import get_memory  # noqa: E402

# where finished GDS live (NOT the per-step runs/ intermediates)
ROOTS = [REPO / "output", REPO / "data" / "ip_library", REPO / "data" / "chip_studio",
         REPO / "examples"]


def _design_of(p: Path) -> str:
    """The owning design = the folder directly under output/ (or ip_library/chip_studio),
    not the deep run-step dir the GDS happens to sit in."""
    parts = p.relative_to(REPO).parts
    for anchor in ("output", "ip_library", "chip_studio", "examples"):
        if anchor in parts:
            i = parts.index(anchor)
            return parts[i + 1] if i + 1 < len(parts) else anchor
    return p.parent.name


def _final_gds() -> list[Path]:
    out, seen = [], set()
    for root in ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.gds"):
            rel = str(p)
            # keep the final/per-design GDS, drop deep run-step intermediates
            if "/runs/" in rel and "/final/" not in rel:
                continue
            if p in seen:
                continue
            seen.add(p)
            out.append(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mem = get_memory()
    if not args.dry_run and not mem.enabled:
        print("knowledge store is DOWN (start docker: `docker compose up -d`) — nothing ingested.")
        return

    gds = _final_gds()
    print(f"found {len(gds)} GDS file(s):")
    by_hash: dict[str, Path] = {}
    ingested = skipped = 0
    for p in sorted(gds, key=lambda x: x.stat().st_size):
        try:
            h = hashlib.sha1(p.read_bytes()).hexdigest()[:16]
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️  {p}: {e}")
            continue
        dup = h in by_hash
        design = _design_of(p)
        size_kb = p.stat().st_size // 1024
        tag = "DUP" if dup else ("would ingest" if args.dry_run else "ingest")
        print(f"  [{tag}] {p.relative_to(REPO)}  ({size_kb} KB, design={design})")
        if dup:
            skipped += 1
            continue
        by_hash[h] = p
        if not args.dry_run:
            okey = f"anoa/gds/{design}__{p.name}"
            rid = mem.remember(
                "gds", f"GDSII layout: {p.name} (design: {design}, {size_kb} KB)",
                design=design, source=f"gds:{design}", title=p.name,
                object_local_path=p, object_key=okey,
                tags="gds layout tapeout", meta={"sha1": h, "size_kb": size_kb})
            if rid:
                ingested += 1
    if args.dry_run:
        print(f"\ndry-run: {len(by_hash)} unique GDS, {skipped} duplicate(s).")
    else:
        print(f"\n✓ ingested {ingested} GDS into Postgres+MinIO ({skipped} duplicate(s) skipped). "
              f"store total now {mem.stats().get('total')}.")


if __name__ == "__main__":
    main()
