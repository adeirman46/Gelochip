#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Stage a MINIMAL gf180 PDK into ./pdk/ for the Docker build.
#
# The full open_pdks gf180mcu (via volare) is ~7.5 GB, almost all of which is
# digital standard cells (libs.ref) and klayout DRC decks. The Kaizen agent's
# Magic-based DRC + ngspice testbenches only need libs.tech/{magic,ngspice,
# netgen,…} — ~3 MB. This script copies just those from a local volare install
# so the Docker image stays small and builds offline (no flaky 7.5 GB download).
#
# Usage:  ./scripts/stage_pdk.sh            (auto-detects $PDK_ROOT/volare)
#         PDK_ROOT=/path/to/pdks ./scripts/stage_pdk.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")/.."

PDK_ROOT="${PDK_ROOT:-$HOME/pdks}"
VARIANT="gf180mcuD"
SUBDIRS="magic ngspice netgen xschem xyce openlane qflow"

# locate the enabled variant dir (volare symlinks PDK_ROOT/gf180mcuD → version)
SRC="$PDK_ROOT/$VARIANT"
if [ ! -d "$SRC/libs.tech/magic" ]; then
  # fall back to the newest volare version dir
  SRC="$(ls -d "$PDK_ROOT"/volare/gf180mcu/versions/*/"$VARIANT" 2>/dev/null | head -1)"
fi
if [ -z "$SRC" ] || [ ! -d "$SRC/libs.tech/magic" ]; then
  echo "ERROR: gf180 PDK not found under $PDK_ROOT. Install it first:"
  echo "   volare enable --pdk gf180mcu 0fe599b2afb6708d281543108caf8310912f54af"
  exit 1
fi

echo "[stage_pdk] source: $SRC"
rm -rf pdk
mkdir -p "pdk/$VARIANT/libs.tech"
[ -f "$SRC/SOURCES" ] && cp "$SRC/SOURCES" "pdk/$VARIANT/"
for d in $SUBDIRS; do
  [ -d "$SRC/libs.tech/$d" ] && cp -r "$SRC/libs.tech/$d" "pdk/$VARIANT/libs.tech/"
done

echo "[stage_pdk] staged $(du -sh pdk | cut -f1) into ./pdk (magicrc: $(ls pdk/$VARIANT/libs.tech/magic/*.magicrc 2>/dev/null | xargs -n1 basename))"
