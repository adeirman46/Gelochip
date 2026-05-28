from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.cells.elementary.transmission_gate.transmission_gate import transmission_gate
# substrate_tap=True adds the p+ guard ring the failing dataset version omitted.
component = transmission_gate(gf180_mapped_pdk, width=(1, 2), length=(0.5, 0.5),
                              substrate_tap=True)
component.name = "TGATE"
