"""Tests for Gelochip core primitives."""
import pytest

try:
    from gelochip.glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
    GLAYOUT_AVAILABLE = True
except ImportError:
    GLAYOUT_AVAILABLE = False


@pytest.mark.skipif(not GLAYOUT_AVAILABLE, reason="gdsfactory/glayout not installed")
class TestFET:
    def test_nmos_default(self):
        from gelochip.core.primitives.fet import nmos
        comp = nmos(pdk)
        assert comp is not None
        assert "gate" in " ".join(comp.ports.keys()).lower() or len(comp.ports) > 0

    def test_pmos_default(self):
        from gelochip.core.primitives.fet import pmos
        comp = pmos(pdk)
        assert comp is not None

    def test_nmos_multi_finger(self):
        from gelochip.core.primitives.fet import nmos
        comp = nmos(pdk, width=4.0, fingers=8)
        assert comp is not None

    def test_pmos_multi_finger(self):
        from gelochip.core.primitives.fet import pmos
        comp = pmos(pdk, width=8.0, fingers=4, multipliers=2)
        assert comp is not None


@pytest.mark.skipif(not GLAYOUT_AVAILABLE, reason="gdsfactory/glayout not installed")
class TestPassives:
    def test_mimcap(self):
        from gelochip.core.primitives.passive import mimcap
        comp = mimcap(pdk, width=5.0, length=5.0)
        assert comp is not None

    def test_via_stack(self):
        from gelochip.core.primitives.via import via_stack
        comp = via_stack(pdk, "active_diff", "met1")
        assert comp is not None
