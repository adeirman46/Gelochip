#!/bin/sh
# Open a schematic in the xschem GUI (runs inside the pandachip-eda
# container, window appears on the host display).
#
# Usage: scripts/xschem_gui.sh designs/dbm-run1/dbm_tb.sch [rawfile.raw]
#
# If a rawfile is given, it is loaded into xschem so transient waveforms
# can be probed/graphed directly in the GUI (xschem 3.4 embedded graphs).
set -e
PANDACHIP_ROOT=$(cd "$(dirname "$0")/.." && pwd)
SCH=$(realpath "$1")
DISPLAY="${DISPLAY:-:0}" xhost +SI:localuser:"$(id -un)" +local: >/dev/null 2>&1 || true

TCL=""
if [ -n "$2" ]; then
  RAW=$(realpath "$2")
  TCL="xschem raw_read $RAW tran"
fi

exec docker exec -d \
  -e PWD="$(dirname "$SCH")" \
  -w "$(dirname "$SCH")" \
  -e DISPLAY="${DISPLAY:-:0}" \
  -e PDK_ROOT=/foss/pdks \
  -e PDK="${PANDACHIP_PDK:-gf180mcuD}" \
  -e PATH=/headless/.local/bin:/foss/tools/bin:/foss/tools/sak:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  pandachip-eda xschem --tcl "$TCL" "$SCH"
