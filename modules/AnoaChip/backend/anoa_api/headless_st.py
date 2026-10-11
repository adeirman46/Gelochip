"""A headless stand-in for `streamlit`, so AnoaChip's existing pipeline
(`src/anoa_chip/app.py`) runs unchanged inside the FastAPI backend — every `st.*`
UI call becomes inert, while the pipeline's own `Recorder` still accumulates its blocks
(which the runner streams to the web UI). Install it BEFORE importing the pipeline:

    from anoa_api import headless_st; headless_st.install()
    import app   # now `import streamlit as st` resolves to this shim
"""
from __future__ import annotations

import sys


class _NoOp:
    """Inert, chainable, falsy stand-in: callable, context-manager, any attribute."""
    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, name):
        return _NoOp()

    def __bool__(self):           # st.button(...) / st.checkbox(...) -> falsy
        return False

    def __iter__(self):
        return iter([])


_noop = _NoOp()


class _SessionState(dict):
    """st.session_state — attribute + item access over a dict."""
    def __getattr__(self, name):
        return self.get(name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        self.pop(name, None)


class _Components:
    def html(self, *a, **k):
        return None

    def iframe(self, *a, **k):
        return None

    def declare_component(self, *a, **k):
        return _noop


class _ST:
    """The `streamlit` module surface the pipeline touches — all no-ops except the few
    that need real behaviour (decorators, session_state, layout helpers)."""
    def __init__(self):
        self.session_state = _SessionState()
        self.components = _ComponentsModule()
        self.sidebar = _NoOp()

    def __getattr__(self, name):       # any other st.X(...) -> inert no-op
        return _noop

    # decorators: support @st.cache_resource and @st.cache_resource(show_spinner=...)
    def cache_resource(self, *a, **k):
        if a and callable(a[0]) and not k:
            return a[0]
        return lambda fn: fn

    cache_data = cache_resource

    # layout / control helpers used in real control flow
    def columns(self, spec, *a, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [_NoOp() for _ in range(max(1, n))]

    def tabs(self, labels, *a, **k):
        return [_NoOp() for _ in labels]

    def set_page_config(self, *a, **k):
        return None

    def rerun(self, *a, **k):
        return None

    def stop(self, *a, **k):
        return None

    def empty(self, *a, **k):
        return _NoOp()

    def spinner(self, *a, **k):
        return _NoOp()

    def expander(self, *a, **k):
        return _NoOp()

    def container(self, *a, **k):
        return _NoOp()

    def form(self, *a, **k):
        return _NoOp()


class _ComponentsModule:
    """Mirrors `streamlit.components` with a `.v1` attribute."""
    def __init__(self):
        self.v1 = _Components()


def install() -> "_ST":
    """Register the shim in sys.modules so `import streamlit` (and
    `import streamlit.components.v1`) resolve to it. Idempotent."""
    if isinstance(sys.modules.get("streamlit"), _ST):
        return sys.modules["streamlit"]
    st = _ST()
    sys.modules["streamlit"] = st
    comps = _ComponentsModule()
    sys.modules["streamlit.components"] = comps
    sys.modules["streamlit.components.v1"] = comps.v1
    return st
