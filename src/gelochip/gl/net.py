"""
Electrical nets — named wires that connect device terminals.

Usage::

    vin  = gl.Net('vin')
    vout = gl.Net('vout')

    mp = gl.pmos(w=4, g=vin, d=vout, s=gl.vdd)
    mn = gl.nmos(w=2, g=vin, d=vout, s=gl.gnd)

Power rails are singletons accessible as gl.vdd / gl.gnd / gl.vss.
"""
from __future__ import annotations


class Net:
    """Named electrical node."""

    _counter = 0

    def __init__(self, name: str = ""):
        if not name:
            Net._counter += 1
            name = f"net{Net._counter}"
        self.name = name
        self.is_power: bool = False    # True for VDD / GND
        self.is_pin: bool = False      # True for circuit I/O ports

    def __repr__(self) -> str:
        return f"Net('{self.name}')"


# ─── Global power / ground singletons ────────────────────────────────────────

class _PowerNet(Net):
    def __init__(self, name: str):
        super().__init__(name)
        self.is_power = True


vdd = _PowerNet("vdd")
vcc = vdd          # alias
gnd = _PowerNet("gnd")
vss = gnd          # alias
