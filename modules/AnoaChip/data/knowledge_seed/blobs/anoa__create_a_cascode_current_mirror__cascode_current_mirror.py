# cascode_current_mirror — glayout current-mirror cell (nfet), emitted DETERMINISTICALLY from the
# config. Uses glayout's OWN verified generator: interdigitized + shorted source/gate +
# diode-connected reference + dummies tied to the tapring + a built-in LVS netlist. This is
# DRC- and LVS-clean by construction (no hand-routing that could cross a device).
from glayout import MappedPDK
from glayout.cells.elementary.current_mirror.current_mirror import current_mirror, add_cm_labels
from gdsfactory import Component


def build(pdk: MappedPDK) -> Component:
    # width/length/fingers pass through to the interdigitized multiplier; with_tie adds the
    # tapring LAST and routes the dummies to it; add_cm_labels stamps VSS/VREF/VCOPY/VB.
    cm = current_mirror(pdk, numcols=2, device="nfet",
                        with_dummy=True, with_tie=True,
                        width=5.0, length=1.0, fingers=1)
    cm = add_cm_labels(cm, pdk)
    return cm
