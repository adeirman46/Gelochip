"""Extract a notebook's canonical build into self-contained clean.py source."""
import json, re

HEADER = (
    "import sys as _sys\n"
    "_sys.setrecursionlimit(8000)\n"
    "class _ModProxy:\n"
    "    def __init__(self, g): self.__dict__ = g\n"
    "_sys.modules[__name__] = _ModProxy(globals())\n\n"
)
STRIP_CALL = ('.drc_magic(', '.lvs_netgen(', 'run_evaluation(', '.write_gds(')
SIM_MARKERS = ('run_spice_gf180(', 'run_testbenches(', '_tb.run_testbenches',
               'gelochip.kaizen import testbench')

def build_source(nb_path, ncells=2):
    nb = json.load(open(nb_path))
    cells = [''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code']
    keep = cells[:ncells]
    code = '\n\n'.join(keep)
    code = re.sub(r'if __name__\s*==\s*[\'"]__main__[\'"]\s*:', 'if True:', code)
    # Faithful DRC heal #1: label pin squares are 0.27um on met2 -> violates gf180
    # M2.1 min width (0.28). Bump to 0.30 (invisible marker, identical topology).
    code = re.sub(r'size=\(0\.27\s*,\s*0\.27\)', 'size=(0.30,0.30)', code)
    out = []
    for ln in code.split('\n'):
        s = ln.lstrip()
        if s.startswith('def ') or s.startswith('#'):
            out.append(ln); continue
        if re.match(r'show_gds\(', s) or any(k in ln for k in STRIP_CALL):
            out.append(ln[:len(ln)-len(s)] + 'pass')
        else:
            out.append(ln)
    body = '\n'.join(out)
    tail = (
        "\n\n# --- bind `component` (kaizen clean entrypoint) ---\n"
        "try:\n"
        "    component\n"
        "except NameError:\n"
        "    import gdsfactory as _gf\n"
        "    _cs = [v for v in list(globals().values()) if isinstance(v, _gf.Component)]\n"
        "    component = _cs[-1] if _cs else None\n"
    )
    heal = (
        "\n\n# --- gf180 metal-spacing DRC heal (KLayout, connectivity-safe: shaves only\n"
        "# empty gaps between shapes, keeps every route >= min width; cannot join nets) ---\n"
        "try:\n"
        "    import tempfile as _tf\n"
        "    _pre = _tf.mktemp(suffix='_pre.gds'); _hl = _tf.mktemp(suffix='_heal.gds')\n"
        "    component.write_gds(_pre)\n"
        "    from glayout.util.drc_heal import heal_spacing as _heal_spacing\n"
        "    _b, _a = _heal_spacing(_pre, _hl)\n"
        "    if _b:\n"
        "        import gdsfactory as _gf2\n"
        "        _nm = component.name\n"
        "        component = _gf2.import_gds(_hl); component.name = _nm\n"
        "        print(f'[heal] metal-spacing {_b}->{_a}')\n"
        "except Exception as _e:\n"
        "    print('heal skipped:', _e)\n"
    )
    return HEADER + body + tail + heal

if __name__ == '__main__':
    import sys
    print(build_source(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 2))
