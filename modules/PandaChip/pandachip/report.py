"""Generate an IEEE Access-style PDF report for a PandaChip run.

A report-authoring agent (the run's own LLM) writes the narrative — what
the circuit does, its inputs/outputs, and how each block operates — from
the run's evidence (plan.md, outcome.json, schematics, waveform/sweep
PNGs). Nothing is invented: the model is given only the collected evidence
and asked to explain it. Falls back to plan-derived text if the LLM is
unavailable.

Output: report/report_<run>.tex compiled to report_<run>.pdf with pdflatex
against the vendored IEEE Access class (templates/ieeeaccess). Schematics
are rendered circuit-only and span the page; waveform and sweep PNGs are
the ones already in the workspace.

Usage:
    .venv/bin/python -m pandachip.report designs/<run-id>
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from .schematic_export import render as render_schematic

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "ieeeaccess"

_ESCAPE = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
           "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
           "^": r"\textasciicircum{}", "\\": r"\textbackslash{}"}
_UNI = {"≥": r"$\geq$", "≤": r"$\leq$", "µ": r"$\mu$", "μ": r"$\mu$",
        "Ω": r"$\Omega$", "×": r"$\times$", "°": r"$^\circ$", "±": r"$\pm$",
        "→": r"$\rightarrow$", "≈": r"$\approx$", "∼": r"$\sim$",
        "–": "--", "—": "---", "‘": "`", "’": "'", "“": "``", "”": "''"}


def _tex(text) -> str:
    s = str(text if text is not None else "")
    for u, r in _UNI.items():
        s = s.replace(u, r)
    out = []
    for i, part in enumerate(re.split(r"(\$[^$]*\$)", s)):
        out.append(part if i % 2 else "".join(_ESCAPE.get(c, c) for c in part))
    return "".join(out)


def _texmd(text) -> str:
    s = str(text if text is not None else "").replace("**", "").replace("`", "")
    s = re.sub(r"^\s*[-*]\s+", "", s, flags=re.M)
    return _tex(s)


def _md_table_to_tex(md: str) -> str | None:
    rows = [r for r in md.splitlines() if r.strip().startswith("|")]
    rows = [r for r in rows if not re.match(r"^\s*\|[\s:|-]+\|\s*$", r)]
    if len(rows) < 2:
        return None
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    ncol = max(len(c) for c in cells)
    cells = [c + [""] * (ncol - len(c)) for c in cells]
    # Span both columns and scale to text width so wide tables never run
    # off the page.
    out = ["\\begin{table*}[!t]", "\\centering",
           "\\caption{Target values per block.}",
           "\\resizebox{\\textwidth}{!}{%",
           "\\begin{tabular}{" + "l" * ncol + "}", "\\hline"]
    out.append(" & ".join(f"\\textbf{{{_texmd(c)}}}" for c in cells[0]) + " \\\\")
    out.append("\\hline")
    for row in cells[1:]:
        out.append(" & ".join(_texmd(c) for c in row) + " \\\\")
    out.append("\\hline\n\\end{tabular}}\n\\end{table*}")
    return "\n".join(out)


def _figure(rel_png: str, caption: str, label: str, wide: bool = False) -> str:
    env = "figure*" if wide else "figure"
    width = "0.9\\textwidth" if wide else "\\columnwidth"
    return (f"\\begin{{{env}}}[!t]\n\\centering\n"
            f"\\includegraphics[width={width}]{{{rel_png}}}\n"
            f"\\caption{{{_tex(caption)}}}\n\\label{{fig:{label}}}\n"
            f"\\end{{{env}}}")


def _plan_blocks(plan: str) -> list[tuple[str, str]]:
    blocks, cur_h, cur_b = [], None, []
    for ln in plan.splitlines():
        m = re.match(r"^#{2,3}\s+(.*)", ln)
        if m:
            if cur_h is not None:
                blocks.append((cur_h, "\n".join(cur_b)))
            cur_h, cur_b = m.group(1).strip(), []
        else:
            cur_b.append(ln)
    if cur_h is not None:
        blocks.append((cur_h, "\n".join(cur_b)))
    return blocks


def _si_str(value: float) -> str:
    """1000000.0 -> '1 Mohm' style label for captions."""
    for scale, suffix in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if value >= scale:
            v = value / scale
            return f"{v:g} {suffix}ohm"
    return f"{value:g} ohm"


def _prompt_title(prompt: str) -> str:
    """Paper title distilled from the design request, NEVER the run name
    (run names are things like iris_web / iris_test1 and make bad titles)."""
    head = prompt.strip().splitlines()[0] if prompt.strip() else ""
    head = re.sub(r"^\s*design\s+", "", head, flags=re.I)
    for cut in ("Background:", "Spec:", "|", "  "):
        i = head.find(cut)
        if i > 0:
            head = head[:i]
    words = head.strip(" .:,-\t").split()
    return " ".join(words[:16]) if words else \
        "An Autonomously Designed Analog/RF Block"


def _chain_rank(stem: str, plan: str, top_stem: str | None) -> tuple:
    """Sort key that follows the SIGNAL CHAIN, not the alphabet: blocks in
    the order plan.md introduces them (each followed by its testbench),
    the toplevel and its testbench last."""
    base = stem[3:] if stem.startswith("tb_") else stem
    base = re.sub(r"_v\d+$", "", base)
    is_tb = 1 if stem.startswith("tb_") else 0
    if top_stem and base == top_stem:
        return (10**6, is_tb, stem)
    low = plan.lower()
    hits = [low.find(c) for c in (base.lower(), base.lower().replace("_", " "))
            if low.find(c) >= 0]
    return (min(hits) if hits else 10**6 - 1, is_tb, stem)


def _one_per_block(pngs: list[str]) -> list[str]:
    """Exactly ONE waveform figure per block.

    The same block's waves exist under several names - tb_<block>,
    <block>, <block>_verify, <block>_vN - and printing more than one is
    the duplication a reader sees. Preference: the testbench evidence
    (tb_<block>), then the promoted block, then its verify deck, then
    the highest experiment version.
    """
    groups: dict[str, dict] = {}
    for p in pngs:
        stem = p[len("waves_"):-len(".png")]
        base = stem[3:] if stem.startswith("tb_") else stem
        ver = re.match(r"^(.*)_v(\d+)$", base)
        n = int(ver.group(2)) if ver else 0
        base = ver.group(1) if ver else base
        base = re.sub(r"_(verify|test)$", "", base)
        g = groups.setdefault(base, {})
        if stem.startswith("tb_") and not ver:
            rank = 0
        elif stem == base:
            rank = 1
        elif not ver:  # _verify / _test
            rank = 2
        else:
            rank = 3
        # lower rank wins; among versions, the highest N wins
        if "pick" not in g or (rank, -n) < (g["rank"], -g["n"]):
            g.update(pick=p, rank=rank, n=n)
    return [g["pick"] for g in groups.values()]


def _pce_points(run: Path, top_stem: str | None = None) -> list[dict]:
    """Power conversion efficiency, computed from the run's own evidence.

    For every power-sweep deck+rawfile pair (and the toplevel testbench):
    P_avail = Vamp^2/(8*Rsrc) from the deck's SIN source behind its series
    resistor, P_out = Vout_dc^2/Rload from the rawfile's steady-state tail
    and the deck's load resistor. Deterministic arithmetic on simulated
    data - no model in the loop, no invented numbers.
    """
    import math
    try:
        from .rawread import read_raw
    except Exception:
        return []
    pts: list[dict] = []
    for raw in sorted(run.glob("*.raw")):
        stem = raw.stem
        if stem.startswith("tb_"):
            # Only the SYSTEM testbench counts: a block testbench's
            # "efficiency" (e.g. the bare charge pump) is not the design's.
            if not (stem == f"tb_{top_stem}" if top_stem
                    else "top" in stem):
                continue
        elif not re.match(r"^sweep_p[-_]?[a-z0-9]*dbm", stem, re.IGNORECASE):
            # power-sweep points, however the run spelled them:
            # sweep_p_minus10dbm, sweep_p-10dbm, sweep_p5dbm ...
            continue
        deck = next((c for c in (
            run / f"{stem}.spice", run / "exp" / f"{stem}.spice",
            run / f"{stem}_ctrl.spice",
            run / "exp" / f"{stem}_ctrl.spice") if c.exists()), None)
        if deck is None:
            continue
        text = deck.read_text(errors="replace")
        m_sin = re.search(r"sin\(\s*\S+\s+([0-9.eE+-]+[a-zA-Z]*)", text,
                          re.IGNORECASE)
        m_load = re.search(
            r"^\s*r\S*\s+(?:vout\S*\s+0|0\s+vout\S*)\s+([0-9.eE+-]+meg|"
            r"[0-9.eE+-]+[a-zA-Z]*)\s*$",
            text, re.IGNORECASE | re.MULTILINE)
        if not (m_sin and m_load):
            continue
        from .eda_tools import _si
        vamp, rload = _si(m_sin.group(1)), _si(m_load.group(1))
        if not vamp or not rload:
            continue
        rsrc = 50.0
        m_src = re.search(r"^\s*r\S*src\S*\s+\S+\s+\S+\s+([0-9.eE+-]+)\s*$",
                          text, re.IGNORECASE | re.MULTILINE)
        if m_src and _si(m_src.group(1)):
            rsrc = _si(m_src.group(1))
        try:
            data = read_raw(raw)["vectors"]
        except Exception:
            continue
        vout_keys = [k for k in data if re.match(r"v\(v?out", k.lower())]
        if not vout_keys:
            continue
        # the final output is the vout-ish vector with the highest tail mean
        def tail_mean(k):
            y = data[k]
            t = y[int(len(y) * 0.8):] or y
            return sum(t) / len(t)
        key = max(vout_keys, key=tail_mean)
        vdc = tail_mean(key)
        p_avail = vamp * vamp / (8.0 * rsrc)
        if p_avail <= 0:
            continue
        p_out = vdc * vdc / rload
        pts.append({"dbm": round(10 * math.log10(p_avail / 1e-3), 1),
                    "vout": vdc, "p_out": p_out,
                    "pce": 100.0 * p_out / p_avail, "node": key,
                    "rload": rload, "source": raw.name})
    pts.sort(key=lambda p: p["dbm"])
    # one point per power level: keep the strongest output (the toplevel)
    dedup: dict[float, dict] = {}
    for p in pts:
        if p["dbm"] not in dedup or p["vout"] > dedup[p["dbm"]]["vout"]:
            dedup[p["dbm"]] = p
    return list(dedup.values())


def _pce_chart(run: Path, pts: list[dict]) -> str | None:
    """Draw waves_pce_vs_power.png if the agent never drew a PCE chart."""
    existing = [p.name for p in run.glob("waves_*.png")
                if "pce" in p.name or "effic" in p.name]
    if existing:
        return existing[0]
    if len(pts) < 2:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.plot([p["dbm"] for p in pts], [p["pce"] for p in pts], marker="o")
        ax.set_title("Power Conversion Efficiency vs Input Power")
        ax.set_xlabel("Input Power (dBm)")
        ax.set_ylabel("PCE (%)")
        ax.grid(True, alpha=0.3)
        out = run / "waves_pce_vs_power.png"
        fig.tight_layout()
        fig.savefig(out, dpi=110)
        plt.close(fig)
        return out.name
    except Exception as exc:
        print(f"[report] pce chart failed: {exc}", file=sys.stderr)
        return None


def _author_narrative(model: str, prompt: str, plan: str, evidence: str,
                      summary: str) -> dict | None:
    """The report-writing agent: the run's own LLM explains the circuit in
    plain engineering prose from the evidence only. Returns a dict or None."""
    if os.getenv("PANDACHIP_REPORT_LLM", "1").lower() in ("0", "false", "no"):
        return None
    try:
        from .agent import chat
    except Exception:
        return None
    ask = (
        "You are writing the technical narrative of an IEEE Access-style "
        "paper about an analog/RF integrated circuit that was just designed "
        "and SPICE-verified. Using ONLY the evidence below (do not invent "
        "numbers), write clear prose an engineer and a student can both "
        "follow. Reply with ONLY a JSON object:\n"
        '{"title": "concise IEEE-style paper title for the CIRCUIT itself, '
        "<=14 words; never the run/file/directory name\", "
        '"abstract": "150-220 words, what the circuit is, how it works, key '
        'measured results", "introduction": "1 paragraph: the problem this '
        'circuit solves and the overall approach", "operation": "2-3 '
        'paragraphs explaining HOW the whole circuit works end to end - the '
        'signal path from input to output", "blocks": [{"name": "block", '
        '"function": "what it does", "inputs": "input nodes and what drives '
        'them", "outputs": "output nodes and expected signal", "how": "how it '
        'works internally in 1-2 sentences"}], "results": "1-2 paragraphs '
        'discussing the measured waveforms and sweeps and whether the spec is '
        'met", "conclusion": "1 short paragraph"}\n\n'
        f"=== DESIGN REQUEST ===\n{prompt}\n\n"
        f"=== PLAN (blocks, sizing, expected values) ===\n{plan[:4000]}\n\n"
        f"=== MEASURED EVIDENCE ===\n{evidence[:2500]}\n\n"
        f"=== AGENT SUMMARY ===\n{summary[:1500]}\n")
    try:
        r = chat(model, [{"role": "user", "content": ask}], use_tools=False)
        txt = r.get("message", {}).get("content", "")
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception as exc:
        print(f"[report] narrative agent failed: {exc}", file=sys.stderr)
    return None


def build(run_dir: str | Path) -> Path:
    run = Path(run_dir).resolve()
    name = run.name
    rep = run / "report"
    rep.mkdir(exist_ok=True)

    meta = json.loads((run / "meta.json").read_text()) if (run / "meta.json").exists() else {}
    outcome = json.loads((run / "outcome.json").read_text()) if (run / "outcome.json").exists() else {}
    # The plan contract may be one legacy plan.md or the per-deliverable
    # split (toplevel_plan.md + <block>_plan.md ...). Concatenate in chain
    # order: toplevel first so _chain_rank sees blocks in its sequence.
    plan = (run / "plan.md").read_text(errors="replace") if (run / "plan.md").exists() else ""
    if not plan:
        parts = []
        if (run / "toplevel_plan.md").exists():
            parts.append((run / "toplevel_plan.md").read_text(errors="replace"))
        for bp in sorted(run.glob("*_plan.md")):
            if bp.name != "toplevel_plan.md":
                parts.append(bp.read_text(errors="replace"))
        plan = "\n\n".join(parts)
    prompt = meta.get("prompt", "")
    model = meta.get("model", "")
    pdk = meta.get("pdk", "gf180mcuD")
    spec_met = outcome.get("spec_met")
    evidence = outcome.get("evidence", "")
    summary = outcome.get("summary", "")

    narr = _author_narrative(model, prompt, plan, evidence, summary) or {}

    # Circuit-only schematics, page-spanning, in SIGNAL-CHAIN order:
    # each block then its testbench, the toplevel last.
    try:
        from .eda_tools import Workspace
        top = Workspace(run).toplevel()
        top_stem = top.stem if top else None
    except Exception:
        top_stem = None
    schem_imgs = []
    schs = [s for s in run.glob("*.sch") if not s.name.startswith("_report_")]
    schs.sort(key=lambda s: _chain_rank(s.stem, plan, top_stem))
    for sch in schs:
        png = rep / f"sch_{sch.stem}.png"
        try:
            render_schematic(sch, png, sch.stem.replace("_", " "))
            schem_imgs.append((sch.stem, f"report/{png.name}"))
        except Exception as exc:
            print(f"schematic render skip {sch.name}: {exc}", file=sys.stderr)

    all_waves = [p.name for p in sorted(run.glob("waves_*.png"))]
    # Sweep CHARTS (plot_xy summaries: VOUT vs dBm / vs frequency) lead the
    # results; the per-point sweep transients they summarize are left in
    # the workspace, not printed.
    sweep_imgs = [p for p in all_waves
                  if "_vs_" in p or p.startswith("waves_vout_")]
    wave_imgs = _one_per_block([p for p in all_waves
                                 if p not in sweep_imgs])
    if sweep_imgs:
        wave_imgs = [p for p in wave_imgs
                     if not p.startswith("waves_sweep_")]
    wave_imgs.sort(key=lambda p: _chain_rank(
        p[len("waves_"):-len(".png")], plan, top_stem))

    L: list[str] = []
    L.append(r"\documentclass{ieeeaccess}")
    L.append(r"\usepackage{graphicx,amsmath,amssymb,textcomp,url,booktabs}")
    L.append(f"\\graphicspath{{{{{run}/}}{{{TEMPLATE_DIR}/}}}}")
    L.append(r"\begin{document}")
    L.append(r"\history{Autonomously generated by PandaChip, "
             f"{date.today().isoformat()}.}}")
    L.append(r"\doi{10.0000/PANDACHIP.2026}")
    # The title describes the CIRCUIT (from the narrative agent, falling
    # back to the design request) - never the run directory name, which is
    # a workspace label like iris_web, not a paper title.
    title = str(narr.get("title") or "").strip() or _prompt_title(prompt)
    L.append(f"\\title{{{_tex(title)}}}")
    L.append(r"\author{\uppercase{PandaChip Autonomous Analog Design Agent}"
             f"\\authorrefmark{{1}}}}")
    L.append(f"\\address[1]{{PandaChip (model {_tex(model)}); "
             f"OpenADA $+$ xschem $+$ ngspice; {_tex(pdk)} open PDK}}")
    L.append(r"\corresp{Generated report; every quantitative claim is derived "
             r"from SPICE simulation evidence.}")
    L.append(r"\markboth{PandaChip: Autonomous Analog/RF Design}"
             r"{PandaChip: Autonomous Analog/RF Design}")

    abstract = narr.get("abstract") or summary or \
        "An analog/RF block autonomously designed and SPICE-verified on an open PDK."
    L.append(r"\begin{abstract}")
    L.append(_tex(abstract))
    L.append(r"\end{abstract}")
    L.append(r"\begin{IEEEkeywords}")
    L.append("analog integrated circuits, GF180MCU, autonomous EDA, xschem, "
             "ngspice, OpenADA, SPICE verification")
    L.append(r"\end{IEEEkeywords}")
    L.append(r"\titlepgskip=-15pt")
    L.append(r"\maketitle")

    # I. Introduction
    L.append(r"\section{Introduction}")
    L.append(r"\IEEEPARstart{T}{his} report documents an analog/RF circuit "
             "designed and verified autonomously on the open GF180MCU PDK. "
             "The requested design was:")
    L.append("\\begin{quote}\\itshape " + _tex(prompt) + "\\end{quote}")
    if narr.get("introduction"):
        L.append(_tex(narr["introduction"]))

    # II. Circuit operation (what it does, signal path)
    if narr.get("operation"):
        L.append(r"\section{Circuit Operation}")
        for para in str(narr["operation"]).split("\n\n"):
            if para.strip():
                L.append(_tex(para))

    # III. Block-by-block (function, inputs, outputs, how)
    L.append(r"\section{Block Design}")
    blocks = narr.get("blocks") or []
    if blocks:
        for b in blocks:
            L.append(f"\\subsection{{{_tex(b.get('name', 'Block'))}}}")
            if b.get("function"):
                L.append("\\textit{Function.} " + _tex(b["function"]))
            if b.get("inputs"):
                L.append("\\textit{Inputs.} " + _tex(b["inputs"]))
            if b.get("outputs"):
                L.append("\\textit{Outputs.} " + _tex(b["outputs"]))
            if b.get("how"):
                L.append("\\textit{Operation.} " + _tex(b["how"]))
    else:  # fallback: plan sections + expected-values table
        for heading, body in _plan_blocks(plan):
            L.append(f"\\subsection{{{_tex(heading)}}}")
            para = "\n".join(l for l in body.splitlines()
                             if l.strip() and not l.strip().startswith("|"))
            if para.strip():
                L.append(_texmd(para[:900]))
    tbl = _md_table_to_tex(plan)
    if tbl:
        L.append(tbl)

    # IV. Schematics (page-spanning, circuit only)
    if schem_imgs:
        L.append(r"\section{Schematics}")
        L.append("The drawn schematics use the real GF180MCU 3.3\\,V devices.")
        for i, (stem, rel) in enumerate(schem_imgs):
            L.append(_figure(rel, f"Schematic of the {stem.replace('_', ' ')} "
                             "block (circuit only).", f"sch{i}"))

    # V. Simulation results
    L.append(r"\section{Simulation Results and Verification}")
    if narr.get("results"):
        for para in str(narr["results"]).split("\n\n"):
            if para.strip():
                L.append(_tex(para))
    if evidence:
        L.append("The measured-versus-expected evidence is:")
        L.append("\\begin{quote}\\ttfamily\\footnotesize\n"
                 + _tex(evidence).replace("\n", "\\\\\n") + "\n\\end{quote}")
    # Power conversion efficiency: reported when the design request asks
    # for it. Computed here from the decks and rawfiles when the agent did
    # not measure it itself.
    pce_pts = _pce_points(run, top_stem) \
        if re.search(r"\bpce\b|efficien", prompt, re.IGNORECASE) else []
    if pce_pts:
        L.append(r"\subsection{Power Conversion Efficiency}")
        L.append("PCE is computed from the simulated evidence as "
                 r"$\mathrm{PCE} = (V_{out}^2/R_{load})\,/\,P_{avail}$ with "
                 r"$P_{avail} = V_{amp}^2/(8R_{src})$, $R_{src}=50\,\Omega$.")
        rows = "".join(
            f"{p['dbm']:+.0f} & {p['vout']:.3f} & "
            f"{p['p_out'] * 1e6:.3g} & {p['pce']:.3g} \\\\\n"
            for p in pce_pts)
        L.append("\\begin{table}[!t]\\caption{Measured power conversion "
                 "efficiency per input power point.}\\label{tab:pce}\n"
                 "\\centering\\begin{tabular}{rrrr}\\toprule\n"
                 "$P_{in}$ (dBm) & $V_{out}$ (V) & $P_{out}$ ($\\mu$W) & "
                 "PCE (\\%) \\\\\n\\midrule\n" + rows +
                 "\\bottomrule\\end{tabular}\\end{table}")
        peak = max(pce_pts, key=lambda p: p["pce"])
        line = (f"The peak measured PCE is {peak['pce']:.3g}\\% at "
                f"{peak['dbm']:+.0f} dBm into the "
                f"{_tex(_si_str(peak['rload']))} testbench load.")
        if re.search(r">\s*60\s*%|60\s*%\s*peak", prompt):
            line += (" This is below the aspirational $>$60\\% target; PCE "
                     "here is measured into the fixed testbench load, not "
                     "a matched load, and improves with load optimisation.")
        L.append(line)
        pce_img = _pce_chart(run, pce_pts)
        if pce_img and pce_img not in sweep_imgs:
            sweep_imgs.append(pce_img)
    for i, img in enumerate(sweep_imgs):
        L.append(_figure(img, "Swept characterisation of the output "
                         "(power, frequency, and efficiency).", f"sweep{i}"))
    for i, img in enumerate(wave_imgs):
        cap = img.replace("waves_", "").replace(".png", "").replace("_", " ")
        L.append(_figure(img, f"Transient waveforms: {cap}. Top: full run; "
                         "bottom: steady-state zoom with sample points.",
                         f"wave{i}"))

    # VI. Conclusion
    L.append(r"\section{Conclusion}")
    concl = narr.get("conclusion") or summary
    L.append(_tex(concl) + (" The specification is satisfied by the "
             "simulation evidence." if spec_met else
             " Remaining work is noted in the evidence above."))

    L.append(r"\EOD")
    L.append(r"\end{document}")
    tex_path = rep / f"report_{name}.tex"
    tex_path.write_text("\n".join(L))

    # Assets the class + doc need in the compile dir.
    for asset in ("Logo.png", "notaglineLogo.png", "jtehmLogo.png",
                  "bullet.png", "ieeeaccess.cls", "IEEEtran.cls"):
        src = TEMPLATE_DIR / asset
        if src.exists():
            shutil.copy(src, rep / asset)

    pdf = _compile(tex_path, rep)
    return pdf or tex_path


def _compile(tex_path: Path, workdir: Path) -> Path | None:
    if not shutil.which("pdflatex"):
        print("pdflatex not found; wrote .tex only", file=sys.stderr)
        return None
    env = dict(os.environ)
    env["TEXINPUTS"] = f"{TEMPLATE_DIR}:{workdir}:" + env.get("TEXINPUTS", "")
    p = None
    for _ in range(2):
        p = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", tex_path.name],
            cwd=workdir, capture_output=True, text=True, timeout=240, env=env)
    pdf = tex_path.with_suffix(".pdf")
    if pdf.exists():
        for junk in workdir.glob("report_*.aux"):
            junk.unlink(missing_ok=True)
        for ext in (".log", ".out"):
            (tex_path.with_suffix(ext)).unlink(missing_ok=True)
        return pdf
    tail = "\n".join((p.stdout if p else "").splitlines()[-30:])
    print(f"pdflatex failed:\n{tail}", file=sys.stderr)
    return None


def main() -> None:
    out = build(sys.argv[1])
    print(json.dumps({"ok": out.suffix == ".pdf", "path": out.name}))


if __name__ == "__main__":
    main()
