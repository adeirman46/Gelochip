#!/usr/bin/env bash
#
# One-time (idempotent) setup for the ALIGN SPICE -> GDS integration.
#
# ALIGN pins pydantic<2, incompatible with the main Gelochip .venv (gelochip,
# gdsfactory, chromadb, langchain... all need pydantic>=2). So ALIGN is built from
# source into a DEDICATED, isolated venv next to this script and is never installed
# into the project .venv.
#
# This script:
#   1. creates the isolated venv  (.venv-align, Python 3.13)
#   2. clones ALIGN to a TEMP build dir, builds it into that venv, then deletes the clone
#   3. extracts the bits we keep:  pdks/  examples/  datasets/CircuitsDatabase/
# Re-running is cheap: it skips the build if `align` already imports, and skips
# extraction for folders that already exist.
#
# Prereqs (already on the dev box): uv, git, gcc/g++>=9, libboost-dev, and the
# system lp-solve package (provides /usr/lib/lp_solve/liblpsolve55.so).
#
# Usage:  bash notebooks/align/setup_align.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv-align"
PROJECT_VENV="$HERE/../../.venv"          # main gelochip venv (has gf180_mapped_pdk)
BUILD="$HERE/.align-build"            # transient clone (deleted at the end)
SRC="$BUILD/ALIGN-public"
SKY_SRC="$BUILD/ALIGN-pdk-sky130"
DEPS="$HERE/.deps"
LP_PREFIX="$DEPS/lpsolve/usr"
LP_SYS_SO="/usr/lib/lp_solve/liblpsolve55.so"
LP_DEB_URL="http://archive.ubuntu.com/ubuntu/pool/universe/l/lp-solve/liblpsolve55-dev_5.5.2.5-2build4_amd64.deb"
REPO="https://github.com/ALIGN-analoglayout/ALIGN-public"
SKY_REPO="https://github.com/ALIGN-analoglayout/ALIGN-pdk-sky130"

echo "==> isolated venv (Python 3.13, pydantic<2)"
[ -x "$VENV/bin/python" ] || uv venv --seed --python 3.13 "$VENV"

have_align() { "$VENV/bin/python" -c "import align" >/dev/null 2>&1; }
need_assets() { [ ! -d "$HERE/pdks" ] || [ ! -d "$HERE/examples" ] || [ ! -d "$HERE/datasets/CircuitsDatabase" ] \
                || [ ! -d "$HERE/pdks/SKY130_PDK" ] || [ ! -d "$HERE/examples/sky130" ]; }

if have_align && ! need_assets; then
  echo "==> already set up — nothing to do."
else
  echo "==> cloning ALIGN + sky130 PDK to transient build dir"
  rm -rf "$BUILD"; mkdir -p "$BUILD"
  git clone --depth 1 "$REPO" "$SRC"
  git clone --depth 1 "$SKY_REPO" "$SKY_SRC"

  if ! have_align; then
    echo "==> lp_solve dev headers (router #includes lp_lib.h; no sudo -> extract .deb)"
    if [ ! -f "$LP_PREFIX/include/lpsolve/lp_lib.h" ]; then
      mkdir -p "$DEPS"
      curl -fsSL -o "$DEPS/lpsolve-dev.deb" "$LP_DEB_URL"
      rm -rf "$DEPS/lpsolve"; dpkg-deb -x "$DEPS/lpsolve-dev.deb" "$DEPS/lpsolve"
    fi
    # .deb static lib is non-PIC; link the system PIC shared lib (link line rpaths $LP_PREFIX).
    [ -e "$LP_SYS_SO" ] || { echo "ERROR: $LP_SYS_SO missing — install lp-solve (sudo apt install lp-solve)"; exit 1; }
    rm -f "$LP_PREFIX/lib/liblpsolve55.a"
    ln -sf "$LP_SYS_SO" "$LP_PREFIX/lib/liblpsolve55.so"

    echo "==> building ALIGN into the isolated venv (C++ engine; a few minutes)"
    export CMAKE_PREFIX_PATH="$LP_PREFIX:${CMAKE_PREFIX_PATH:-}"
    export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-4}"     # keep RAM in check
    ( cd "$SRC" && "$VENV/bin/pip" install -v . )
  fi

  echo "==> extracting pdks / examples / datasets / sky130"
  # GF180_PDK is committed in pdks/, so don't gate on pdks/ existence — merge without clobbering.
  mkdir -p "$HERE/pdks" "$HERE/examples" "$HERE/datasets" "$HERE/examples/sky130"
  cp -rn "$SRC/pdks/." "$HERE/pdks/" 2>/dev/null || true
  cp -rn "$SRC/examples/." "$HERE/examples/" 2>/dev/null || true
  [ -d "$HERE/datasets/CircuitsDatabase" ] || cp -r "$SRC/CircuitsDatabase" "$HERE/datasets/CircuitsDatabase"
  # sky130 real PDK abstraction + its example circuits
  [ -d "$HERE/pdks/SKY130_PDK" ]           || cp -r "$SKY_SRC/SKY130_PDK"   "$HERE/pdks/SKY130_PDK"
  cp -rn "$SKY_SRC/examples/." "$HERE/examples/sky130/" 2>/dev/null || true

  echo "==> removing transient clone"
  rm -rf "$BUILD"
fi

mkdir -p "$HERE/netlists" "$HERE/runs"
# pdks/GF180_PDK (GF180MCU abstraction for ALIGN) is committed in the repo — nothing to build.

echo "==> smoke test"
LD_LIBRARY_PATH="/usr/lib/lp_solve:${LD_LIBRARY_PATH:-}" \
  "$VENV/bin/python" -c "import align; print('ALIGN', align.__version__, 'import OK')"

cat <<EOF

Done.
  • ALIGN installed in : $VENV
  • PDKs               : $HERE/pdks
  • examples           : $HERE/examples
  • datasets           : $HERE/datasets/CircuitsDatabase

Next:
  notebook : open notebooks/align/spice_to_gds.ipynb with the project .venv kernel
  CLI      : ../../.venv/bin/python notebooks/align/spice2gds.py netlists/five_transistor_ota.sp --png
EOF
