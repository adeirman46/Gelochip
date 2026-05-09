#!/usr/bin/env bash
# Parasitic extraction (PEX) via Magic
# Supports gf180 (default) and sky130
#
# Usage:
#   bash scripts/run_pex.sh <layout.gds> <cell_name> [pdk]
#
# Example:
#   bash scripts/run_pex.sh /tmp/gelochip_output/lna_cascode.gds lna_cascode gf180
#
# Requires:
#   - Magic VLSI (sudo apt install magic)
#   - PDK_ROOT environment variable set
#   - ngspice (sudo apt install ngspice) for simulation

set -e

GDS_FILE="${1:?Usage: $0 <layout.gds> <cell_name> [pdk]}"
LAYOUT_CELL="${2:?Usage: $0 <layout.gds> <cell_name> [pdk]}"
PDK="${3:-gf180}"
PDK_ROOT="${PDK_ROOT:?Set PDK_ROOT to your PDK installation directory}"

# ── PDK-specific magic rc file ─────────────────────────────────────────────────
case "$PDK" in
    gf180|gf180mcu)
        MAGICRC="${PDK_ROOT}/gf180mcuD/libs.tech/magic/gf180mcu.magicrc"
        ;;
    sky130)
        MAGICRC="${PDK_ROOT}/sky130A/libs.tech/magic/sky130A.magicrc"
        ;;
    *)
        echo "Unknown PDK: $PDK. Use gf180 or sky130."
        exit 1
        ;;
esac

if [ ! -f "$MAGICRC" ]; then
    echo "Error: Cannot find magicrc at $MAGICRC"
    echo "Make sure PDK_ROOT is set correctly (current: $PDK_ROOT)"
    echo "Install PDK: uv run volare enable --pdk gf180mcu --version 0.0.1"
    exit 1
fi

echo "Running PEX on $GDS_FILE (cell: $LAYOUT_CELL, PDK: $PDK)..."

magic -rcfile "$MAGICRC" -noconsole -dnull << EOF
gds read ${GDS_FILE}
flatten ${LAYOUT_CELL}
load ${LAYOUT_CELL}
select top cell
extract do local
extract all
ext2sim labels on
ext2sim
extresist tolerance 10
extresist
ext2spice lvs
ext2spice cthresh 0
ext2spice extresist on
ext2spice -o ${LAYOUT_CELL}_pex.spice
exit
EOF

echo "PEX complete: ${LAYOUT_CELL}_pex.spice"
echo "Now run simulation:"
echo "  ngspice -b testbench.sp"
