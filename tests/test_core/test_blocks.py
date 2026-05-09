"""Tests for Gelochip building blocks."""
import pytest

try:
    from gelochip.glayout.pdk.gf180_mapped import gf180_mapped_pdk as pdk
    GLAYOUT_AVAILABLE = True
except ImportError:
    GLAYOUT_AVAILABLE = False


@pytest.mark.skipif(not GLAYOUT_AVAILABLE, reason="gdsfactory/glayout not installed")
class TestCurrentMirror:
    def test_basic_nmos(self):
        from gelochip.core.blocks.current_mirror import current_mirror
        comp = current_mirror(pdk, mirror_ratio=1.0, ref_width=4.0, n_or_p="nfet")
        assert comp is not None

    def test_basic_pmos(self):
        from gelochip.core.blocks.current_mirror import current_mirror
        comp = current_mirror(pdk, mirror_ratio=2.0, ref_width=4.0, n_or_p="pfet")
        assert comp is not None

    def test_wilson(self):
        from gelochip.core.blocks.current_mirror import wilson_current_mirror
        comp = wilson_current_mirror(pdk, mirror_ratio=1.0, ref_width=4.0)
        assert comp is not None


@pytest.mark.skipif(not GLAYOUT_AVAILABLE, reason="gdsfactory/glayout not installed")
class TestDiffPair:
    def test_nmos_diff_pair(self):
        from gelochip.core.blocks.diff_pair import diff_pair
        comp = diff_pair(pdk, width=6.0, fingers=4, n_or_p="nfet")
        assert comp is not None


@pytest.mark.skipif(not GLAYOUT_AVAILABLE, reason="gdsfactory/glayout not installed")
class TestAmplifier:
    def test_common_source(self):
        from gelochip.core.blocks.amplifier import common_source
        comp = common_source(pdk, width=4.0, fingers=2, load_type="pmos_diode")
        assert comp is not None

    def test_common_gate(self):
        from gelochip.core.blocks.amplifier import common_gate
        comp = common_gate(pdk, width=4.0, fingers=2)
        assert comp is not None
