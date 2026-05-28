from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.cells.elementary.current_mirror.current_mirror import current_mirror
# Canonical interdigitized current mirror — DRC-clean on gf180 (with_tie adds the
# tap ring). substrate_tap=True adds the guard ring for a fully clean standalone block.
component = current_mirror(gf180_mapped_pdk, numcols=3, device="nfet",
                           with_substrate_tap=True, with_tie=True)
component.name = "CMIRROR"
