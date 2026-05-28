"""
Device — a single element (transistor, cell, passive) with declared net connections.

Devices auto-register with the currently active Module via a thread-local stack.
The same pattern PyTorch uses for automatic layer/parameter registration.

Two modes:
  1. Raw primitive (nmos/pmos/res/cap): port lookup by keyword ("gate", "drain", …)
  2. Pre-built cell (current_mirror/diff_pair/…): port lookup by cell-specific port_map
"""
from __future__ import annotations

import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from gdsfactory.component import Component
from gdsfactory.port import Port

# ─── Active-module stack (thread-local, same idea as PyTorch's _C) ────────────

_tls = threading.local()


def _active_module() -> Optional[Any]:
    stack = getattr(_tls, "stack", [])
    return stack[-1] if stack else None


def _push_module(m: Any) -> None:
    if not hasattr(_tls, "stack"):
        _tls.stack = []
    _tls.stack.append(m)


def _pop_module() -> None:
    stack = getattr(_tls, "stack", [])
    if stack:
        stack.pop()


# ─── Port skip pattern (noise ports we never want to route to) ────────────────

_SKIP = re.compile(
    r"dummy|diff(?!pair)|via|bottom_layer|top_layer|array|plusdoped|"
    r"substrate|pwell|nwell|gsdcon|leftsd|rightsd|purposegnd|con_N$|con_S$|con_E$|con_W$",
    re.I,
)

# ─── Generic terminal → port-keyword mapping (for raw FETs / passives) ────────

_GENERIC_KW = {
    "g": "gate",
    "gate": "gate",
    "d": "drain",
    "drain": "drain",
    "s": "source",
    "source": "source",
    "b": "tie",
    "bulk": "tie",
    "body": "tie",
    "tie": "tie",
    # resistor / cap
    "a": "e1",
    "p": "top_met",
    "n": "bottom_met",
    # bjt
    "c": "collector",
    "e": "emitter",
    "base": "base",
    "collector": "collector",
    "emitter": "emitter",
}

# Direction priority per terminal (prefers this port-name suffix)
_PREF_DIR = {
    "drain": "N",
    "iout": "N",
    "out": "N",
    "source": "S",
    "tail": "S",
    "collector": "N",
    "emitter": "S",
}


def _find_port(ref, keyword: str, prefer_dir: str = "") -> Optional[Port]:
    """
    Search ref.ports for the best port matching `keyword` as a substring.
    Skips structural/dummy ports.  Prefers direction suffix if given.
    """
    candidates: List[Tuple[str, Port]] = [
        (name, port)
        for name, port in ref.ports.items()
        if keyword.lower() in name.lower() and not _SKIP.search(name)
    ]
    if not candidates:
        return None
    pref = prefer_dir or _PREF_DIR.get(keyword.lower(), "E")
    for name, port in candidates:
        if name.endswith(f"_{pref}"):
            return port
    return candidates[0][1]


# ─── Device ──────────────────────────────────────────────────────────────────

class Device:
    """
    A single placed element.  Wraps a gdsfactory Component and holds the
    declared net connections.

    Parameters
    ----------
    kind        : 'nmos' | 'pmos' | 'res' | 'cap' | 'current_mirror' | …
    component   : raw gdsfactory Component (geometry + ports)
    connections : {terminal_name: Net}
    tag         : optional label
    port_map    : {terminal_name: port_keyword}  (cell-specific overrides)
    """

    def __init__(
        self,
        kind: str,
        component: Component,
        connections: Dict[str, Any],   # Any = Net
        tag: str = "",
        port_map: Optional[Dict[str, str]] = None,
    ):
        self.kind = kind
        self.component = component
        self.connections: Dict[str, Any] = connections
        self.tag = tag or f"{kind}_{id(self) & 0xFFFF:04x}"
        self._port_map: Dict[str, str] = port_map or {}
        self._ref: Any = None  # ComponentReference, set during compile

        # auto-register with active Module
        mod = _active_module()
        if mod is not None:
            mod._register_device(self)

    def get_port(self, terminal: str) -> Optional[Port]:
        """
        Resolve terminal name → Port on self._ref.

        Resolution order:
        1. Cell-specific port_map (exact substring match)
        2. Generic keyword map (_GENERIC_KW)
        3. Direct substring search on terminal name
        """
        if self._ref is None:
            return None

        # 1. Cell-specific map
        if terminal in self._port_map:
            kw = self._port_map[terminal]
            port = _find_port(self._ref, kw)
            if port is not None:
                return port

        # 2. Generic map
        kw = _GENERIC_KW.get(terminal, terminal)
        return _find_port(self._ref, kw, _PREF_DIR.get(kw, ""))
