from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.cells.elementary.diff_pair import diff_pair
_r = diff_pair(gf180_mapped_pdk)
component = _r[0] if isinstance(_r, (tuple, list)) else _r
component.name = "DIFF_PAIR"
