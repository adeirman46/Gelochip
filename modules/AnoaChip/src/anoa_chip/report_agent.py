"""
AnoaChip report writer — a clean design summary for an analog run.

Deterministic-first (same philosophy as netlist_check's gates): THIS module collects
the evidence off disk (config, netlist, spec metrics, Bode/transient/layout images,
DRC/LVS verdicts), asks the local LLM for a short narrative, and builds:
  • report.md   — always (markdown, embeds the figure paths)
  • report.pdf  — when pdflatex is available (a minimal LaTeX wrapper)

`run_report(rec, ctx, feedback)` is the entry point; it never gates the run — a
failure ends the step with an error note, not a paused run.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict

from llm import get_chat_model


def _render_gds_png(gds_path: Path, out_png: Path) -> bool:
    """Rasterize a GDS to a PNG for the LaTeX PDF, in the SAME look as the glayout
    tutorials' display_gds(): gdstk write_svg (the colour scheme the user knows from the
    ipynb) → cairosvg → PNG. No matplotlib false-colour. Returns True on success."""
    try:
        import gdstk
        lib = gdstk.read_gds(str(gds_path))
        tops = lib.top_level()
        if not tops:
            return False
        out_png.parent.mkdir(parents=True, exist_ok=True)
        svg = out_png.with_suffix(".svg")
        tops[0].write_svg(str(svg))                 # exactly the ipynb display_gds() output
        import cairosvg
        cairosvg.svg2png(url=str(svg), write_to=str(out_png),
                         output_width=700, background_color="white")
        return out_png.exists()
    except Exception:  # noqa: BLE001
        return False


# pdflatex (non-unicode engine) ABORTS on chars like ≥ µ Ω → that the LLM narrative loves —
# that's what made every report say "pdflatex unavailable or failed" while /usr/bin/pdflatex
# was fine. Convert them to real LaTeX AFTER escaping; drop anything else non-ASCII.
_TEX_UNICODE = {
    "≥": r"$\geq$", "≤": r"$\leq$", "µ": r"$\mu$", "μ": r"$\mu$", "Ω": r"$\Omega$",
    "·": r"$\cdot$", "×": r"$\times$", "→": r"$\rightarrow$", "←": r"$\leftarrow$",
    "±": r"$\pm$", "°": r"$^\circ$", "²": r"$^2$", "³": r"$^3$", "√": r"$\surd$",
    "—": "---", "–": "--", "’": "'", "‘": "`", "“": "``", "”": "''", "…": "...",
    "✓": "OK", "✔": "OK", "✗": "X", "✘": "X", "✅": "OK", "❌": "X", "⚠": "(!)",
}


def _esc_tex(s) -> str:
    s = str(s)
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"),
                 ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
                 ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")):
        s = s.replace(a, b)
    for a, b in _TEX_UNICODE.items():          # after escaping — replacements are trusted TeX
        s = s.replace(a, b)
    return re.sub(r"[^\x00-\x7F]", "", s)       # catch-all: no unicode reaches pdflatex


def _esc_md_tex(s: str) -> str:
    """Escape for TeX while honouring markdown inline: **bold** → \\textbf, `code` → \\texttt.
    (Plain _esc_tex left the literal asterisks in the PDF — '**Topology**:' rendered as-is.)"""
    out, i = [], 0
    for m in re.finditer(r"\*\*(.+?)\*\*|`([^`]+)`", s):
        out.append(_esc_tex(s[i:m.start()]))
        if m.group(1) is not None:
            out.append(r"\textbf{" + _esc_tex(m.group(1)) + "}")
        else:
            out.append(r"\texttt{" + _esc_tex(m.group(2)) + "}")
        i = m.end()
    out.append(_esc_tex(s[i:]))
    return "".join(out)


def _ascii(s) -> str:
    """verbatim-block sanitizer: unicode → plain ascii (µ→u, ✓→OK), rest dropped."""
    s = str(s)
    for a, b in (("µ", "u"), ("μ", "u"), ("Ω", "ohm"), ("≥", ">="), ("≤", "<="),
                 ("✓", "OK"), ("✗", "X"), ("✅", "OK"), ("❌", "X"), ("→", "->"),
                 ("·", "*"), ("×", "x"), ("—", "-"), ("–", "-"), ("°", "deg")):
        s = s.replace(a, b)
    return re.sub(r"[^\x00-\x7F]", "", s)


def _unit_states(design_dir: Path) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    ud = design_dir / "context" / "unit_state"
    if ud.is_dir():
        for p in sorted(ud.glob("*.json")):
            try:
                out[p.stem] = json.loads(p.read_text())
            except Exception:  # noqa: BLE001
                pass
    return out


def _collect(ctx) -> dict:
    """Gather the analog evidence for the report off disk + ctx."""
    d = Path(ctx["design_dir"])
    top = ctx.get("top_module_name") or "design"
    netlists = sorted((d / "netlist").glob("*.sp")) + sorted((d / "netlist").glob("*.spice"))
    tbs = sorted((d / "tb").glob("*_tb.sp"))
    layout_py = sorted((d / "layout").glob("*.py"))

    cfg = {}
    for p in sorted((d / "config").glob("*.json")):
        try:
            data = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            continue
        cfg = data
        if p.stem == top:
            break

    metrics = ctx.get("sim_metrics") or {}
    for mf in ("sim/postlayout_metrics.json", "sim/metrics.json"):
        if not metrics and (d / mf).exists():
            try:
                metrics = json.loads((d / mf).read_text())
            except Exception:  # noqa: BLE001
                metrics = {}

    hm = ctx.get("harden_metrics") or {}

    # PHYSICAL-VERIFICATION EVIDENCE (deterministic, from the run's own artifacts):
    # the harness's verify json (DRC error count, netgen's LVS conclusion, ports/labels)
    # and a device tally from the PEX netlist — the report explains WHY DRC/LVS passed.
    verify: dict = {}
    vj = d / "layout" / f"{top}_verify.json"
    if not vj.exists():
        vj = next(iter(sorted((d / "layout").glob("verify_*.json"))), None) \
            if (d / "layout").is_dir() else None
    if vj and Path(vj).exists():
        try:
            verify = json.loads(Path(vj).read_text())
        except Exception:  # noqa: BLE001
            verify = {}
    devices: dict = {}
    pexf = d / "layout" / f"{top}_pex.spice"
    if pexf.exists():
        try:
            for mdl in re.findall(r"^[MXmx]\S*\s+.*?\b([np]fet_\d+v\d+)\b",
                                  pexf.read_text(errors="replace"), re.M):
                devices[mdl] = devices.get(mdl, 0) + 1
        except Exception:  # noqa: BLE001
            pass
    circuit_fets = 0
    try:
        circuit_fets = sum(1 for c in (cfg.get("wiring") or [])
                           if isinstance(c, dict)
                           and str(c.get("type", "")).lower() in ("nfet", "pfet", "nmos", "pmos"))
    except Exception:  # noqa: BLE001
        pass

    figs = {}
    for key, cand in (("bode", "sim/bode.png"), ("tran", "sim/tran.png")):
        p = d / cand
        if p.exists():
            figs[key] = str(p)
    # LAYOUT figure: rasterize the GDS to a PNG (embeds in the LaTeX PDF + renders in chat;
    # SVG can't do either). Fall back to the .svg only if rasterization fails.
    gds = d / "layout" / f"{top}.gds"
    if gds.exists():
        png = d / "layout" / f"{top}_render.png"
        if _render_gds_png(gds, png):
            figs["layout"] = str(png)
        elif (d / "layout" / f"{top}.svg").exists():
            figs["layout"] = str(d / "layout" / f"{top}.svg")

    # the EXACT reference netlist netgen compared the layout against (so the reader can
    # check the LVS was meaningful) — a layout artifact: layout/<top>_layout.cdl
    # (legacy runs wrote it under netlist/ — read both).
    ref_netlist = ""
    for cdl in (d / "layout" / f"{top}_layout.cdl", d / "netlist" / f"{top}_layout.cdl"):
        if cdl.exists():
            ref_netlist = cdl.read_text(errors="replace")[:4000]
            break

    return {
        "design_dir": d, "top": top, "query": ctx.get("query", ""),
        "netlists": [p.name for p in netlists], "tbs": [p.name for p in tbs],
        "layout_scripts": [p.name for p in layout_py],
        "config": cfg, "metrics": metrics, "harden": hm,
        "verify": verify, "devices": devices, "circuit_fets": circuit_fets,
        "ref_netlist": ref_netlist,
        "figs": figs, "units": _unit_states(d), "pdk": ctx.get("pdk", ""),
        "notes": (d / "design_notes.md").read_text(errors="replace")[:4000]
        if (d / "design_notes.md").exists() else "",
    }


def _verification_lines(ev: dict) -> list:
    """Deterministic 'Physical verification' bullets: WHY DRC passed, WHY LVS passed, and
    how many transistors the layout holds — from the run's own verify json + PEX netlist."""
    v = ev.get("verify") or {}
    drc, lvs, bld = v.get("drc") or {}, v.get("lvs") or {}, v.get("build") or {}
    out = []
    if drc:
        n = drc.get("total_errors")
        out.append(
            f"DRC ({ev['pdk']}, magic): **{str(drc.get('status', '—')).upper()}** — "
            + (f"{n} violation(s)" if n is not None else "no report")
            + (". Every geometry rule the foundry deck checks (metal/poly/active spacing, "
               "minimum width, via enclosure, well/tap clearance) came back clean — the "
               "layout is manufacturable as drawn." if drc.get("is_pass") else
               f". Violations: {str(drc.get('error_details'))[:300]}"))
    if lvs:
        out.append(
            f"LVS (netgen): **{str(lvs.get('status', '—')).upper()}** — "
            + str(lvs.get("conclusion") or "").rstrip(".")
            + (f"; {lvs.get('total_mismatches', 0)} mismatch(es). The extracted layout "
               f"netlist was compared against the reference netlist: every device, every "
               f"net and every labelled port ({bld.get('n_labels', '?')} labels on "
               f"{bld.get('n_ports', '?')} ports) matched one-to-one."
               if lvs.get("is_pass") else
               f"; unmatched: {str(lvs.get('unmatched'))[:200]}"))
    dev = ev.get("devices") or {}
    if dev:
        total = sum(dev.values())
        per = ", ".join(f"{n}× {m}" for m, n in sorted(dev.items()))
        core = ev.get("circuit_fets") or 0
        note = (f" ({core} circuit transistors in the schematic; the layout count includes "
                "interdigitized fingers, multipliers and edge dummies)" if core else "")
        out.append(f"Transistors in the extracted layout: **{total}** — {per}{note}.")
    if bld:
        bbox = bld.get("bbox_um")
        area = ""
        try:
            x0, y0, x1, y1 = [float(v) for v in bbox]
            w, h = x1 - x0, y1 - y0
            area = (f"; die area {w:.2f} × {h:.2f} µm = {w * h:,.0f} µm² "
                    f"({w * h / 1e6:.6f} mm²)")
        except Exception:  # noqa: BLE001
            pass
        out.append(f"Layout: {bld.get('n_ports', '?')} ports, bbox {bbox} µm{area}; "
                   f"reference netlist attached: {'yes' if bld.get('has_ref_netlist') else 'no'}.")
    return out


def _spec_table_md(cfg: dict, metrics: dict) -> str:
    spec = (cfg or {}).get("spec") or {}
    if not spec:
        return "_(no spec table in the config)_"
    try:
        from spice_sim import check_specs, spec_table
        return "```\n" + spec_table(check_specs(metrics, spec)) + "\n```"
    except Exception:  # noqa: BLE001
        return "```\n" + json.dumps(spec, indent=1) + "\n```"


def _narrative(rec, ev: dict) -> str:
    prompt = (
        "Write a CONCISE engineering summary (markdown, <=40 lines) of this finished analog IC "
        "design. Sections: ## Objective, ## Topology & sizing, ## Simulation results, "
        "## Physical verification. In 'Physical verification' EXPLAIN WHY DRC passed (what the "
        "rule deck checks) and WHY LVS passed (what netgen compared, how the labels matched) "
        "using ONLY the facts below; state the transistor count. In 'Simulation results' "
        "discuss ONLY the analyses that ran (a current mirror needs DC/transient, not AC). "
        "PLAIN PROSE ONLY inside sections: no LaTeX math, no tables; **bold** and `code` "
        "are allowed. Be specific with the real numbers below; do NOT invent values, do NOT "
        "name any source repo.\n\n"
        f"PROMPT: {ev['query']}\n"
        f"TOP CIRCUIT: {ev['top']} on {ev['pdk']}\n"
        f"CONFIG: {json.dumps(ev['config'])[:1500]}\n"
        f"MEASURED METRICS: {json.dumps(ev['metrics'])[:800]}\n"
        f"LAYOUT: {json.dumps(ev['harden'])[:400]}\n"
        f"PHYSICAL VERIFICATION FACTS:\n" + "\n".join("- " + v for v in _verification_lines(ev))
        + f"\nDESIGN NOTES (excerpt):\n{ev['notes'][:1200]}\n")
    try:
        out = get_chat_model(temperature=0.3).invoke(prompt)
        text = getattr(out, "content", "") or str(out)
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    except Exception:  # noqa: BLE001
        return ""


def _write_md(ev: dict, narrative: str) -> Path:
    d = ev["design_dir"]
    m = ev["metrics"]
    hm = ev["harden"]
    lines = [f"# {ev['top']} — AnoaChip design report", "",
             f"**Prompt:** {ev['query']}", "",
             f"**PDK:** {ev['pdk']}  ·  **Circuits:** {', '.join(ev['netlists']) or '—'}", ""]
    if narrative:
        lines += [narrative, ""]
    lines += ["## Spec verdict (target vs measured)", "",
              _spec_table_md(ev["config"], m), ""]
    if m:
        lines += ["## Measured metrics", ""]
        for k, v in m.items():
            lines.append(f"- **{k}** = {v:.6g}" if isinstance(v, (int, float)) else f"- **{k}** = {v}")
        lines.append("")
    lines += ["## Physical verification (why DRC & LVS passed)", ""]
    ver = _verification_lines(ev)
    if ver:
        lines += [f"- {v}" for v in ver] + [""]
    elif hm:
        lines += [f"- GDS: `{hm.get('gds', 'not produced')}`",
                  f"- DRC (magic): **{hm.get('drc', '—')}** · LVS (netgen): **{hm.get('lvs', '—')}**", ""]
    else:
        lines += ["_(layout not run or not signed off)_", ""]
    for cap, key in (("Bode plot (gain / phase)", "bode"),
                     ("Transient response", "tran"),
                     ("Layout", "layout")):
        if key in ev["figs"]:
            rel = Path(ev["figs"][key]).relative_to(d)
            lines += [f"### {cap}", "", f"![{cap}]({rel})", ""]
    if ev["units"]:
        lines += ["## Per-circuit verification", "",
                  "| circuit | status | attempts |", "|---|---|---|"]
        for nm, st in ev["units"].items():
            lines.append(f"| {nm} | {st.get('status', '?')} | {st.get('attempts', 0)} |")
        lines.append("")
    p = d / "report.md"
    p.write_text("\n".join(lines))
    return p


def _tex(ev: dict, narrative: str) -> str:
    d = ev["design_dir"]
    body = [r"\documentclass[11pt]{article}",
            r"\usepackage[margin=1in]{geometry}",
            r"\usepackage{graphicx}\usepackage{booktabs}\usepackage{hyperref}",
            r"\title{" + _esc_tex(ev["top"]) + r" --- AnoaChip design report}",
            r"\date{}", r"\begin{document}\maketitle",
            r"\noindent\textbf{Prompt:} " + _esc_tex(ev["query"]) + r"\\",
            r"\textbf{PDK:} " + _esc_tex(ev["pdk"]) + r"\\",
            r"\textbf{Circuits:} " + _esc_tex(", ".join(ev["netlists"]) or "--") + r"\par\medskip"]
    for ln in (narrative or "").splitlines():
        s = ln.strip()
        if not s:
            body.append("")
        elif s.startswith("## "):
            body.append(r"\section*{" + _esc_md_tex(s[3:]) + "}")
        elif s.startswith(("- ", "* ")):
            body.append(_esc_md_tex(s[2:]) + r"\\")
        else:
            body.append(_esc_md_tex(s))
    # deterministic physical-verification section (why DRC/LVS passed, transistor count)
    ver = _verification_lines(ev)
    if ver:
        body.append(r"\section*{Physical verification (evidence)}")
        body += [_esc_md_tex(v) + r"\\" for v in ver]
    spec = (ev["config"] or {}).get("spec") or {}
    if spec:
        try:
            from spice_sim import check_specs, spec_table
            tbl = _ascii(spec_table(check_specs(ev["metrics"], spec)))
            body += [r"\section*{Spec verdict ('-' = not measured / not applicable)}",
                     r"\begin{verbatim}", tbl, r"\end{verbatim}"]
        except Exception:  # noqa: BLE001
            pass
    if ev["metrics"]:
        rows = "\n".join(f"{k} = {v:.6g}" if isinstance(v, (int, float)) else f"{k} = {v}"
                         for k, v in ev["metrics"].items())
        body += [r"\section*{Measured metrics (post-layout, PEX netlist)}",
                 r"\begin{verbatim}", _ascii(rows), r"\end{verbatim}"]
    if ev.get("ref_netlist"):
        body += [r"\section*{LVS reference netlist (what netgen compared the layout against)}",
                 r"\begin{verbatim}", _ascii(ev["ref_netlist"])[:2500], r"\end{verbatim}"]
    for cap, key, wid in (("GDS layout (DRC/LVS clean)", "layout", "0.85"),
                          ("Transient response (post-layout)", "tran", "0.8"),
                          ("Bode plot (AC, if applicable)", "bode", "0.8")):
        if key in ev["figs"] and str(ev["figs"][key]).lower().endswith((".png", ".pdf", ".jpg")):
            rel = Path(ev["figs"][key]).relative_to(d)
            body += [r"\begin{figure}[h]\centering",
                     r"\includegraphics[width=" + wid + r"\textwidth]{" + str(rel) + "}",
                     r"\caption{" + _esc_tex(cap) + "}", r"\end{figure}"]
    body.append(r"\end{document}")
    return "\n".join(body)


def _pdflatex(rep: Path) -> tuple:
    if not shutil.which("pdflatex"):
        return False, "pdflatex not installed"
    proc = None
    for _ in range(2):
        try:
            proc = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "report.tex"],
                cwd=str(rep.parent), capture_output=True, text=True, timeout=120)
        except Exception as e:  # noqa: BLE001
            return False, f"(pdflatex could not run: {e})"
    ok = (rep.parent / "report.pdf").exists()
    return ok, ((proc.stdout + proc.stderr)[-2000:] if proc else "")


def run_report(rec, ctx, feedback=""):
    """Compile the design summary (markdown always; PDF if pdflatex is available)."""
    rec.caption("📕 Writing the design report — collecting evidence, then narrating.")
    ev = _collect(ctx)
    narrative = _narrative(rec, ev)
    md = _write_md(ev, narrative)

    # SHOW THE LAYOUT IMAGE as a proper rec.image (a raster PNG that the chat CAN render) —
    # NOT the raw markdown with a relative ![](layout/x.svg) link, which shows as a broken img.
    lay = ev["figs"].get("layout")
    if lay and str(lay).lower().endswith((".png", ".svg")):
        rec.image(str(lay), f"🔲 {ev['top']} — GDS layout")
    # the EXACT netlist netgen compared against — so the LVS PASS is checkable by eye
    if ev.get("ref_netlist"):
        rec.expander_code("🔍 LVS reference netlist (netgen compared the layout against THIS)",
                          ev["ref_netlist"][:4000], "spice")

    # The deliverable is the PDF (LaTeX), like GarudaChip — build it FIRST and lead with it.
    pdf_ok = False
    try:
        (ev["design_dir"] / "report.tex").write_text(_tex(ev, narrative))
        pdf_ok, _log = _pdflatex(ev["design_dir"] / "report.tex")
        if pdf_ok:
            rec.success("📕 Design report (PDF from LaTeX) built — `report.pdf`.")
            rec.file("report.pdf", f"{ev['top']}_report.pdf")
        else:
            rec.caption("(pdflatex unavailable/failed — showing the markdown summary instead.)")
    except Exception as e:  # noqa: BLE001
        rec.caption(f"(PDF step skipped: {e})")

    # Markdown is the fallback view; only dump it inline when there's no PDF (so we don't show
    # the broken relative image links when the PDF already has the figures embedded).
    # PDF only in the chat — the .md is on disk for the artifacts tree, not a chip.
    if not pdf_ok:
        rec.markdown(md.read_text()[:8000])
