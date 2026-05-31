"""
gelochip.kaizen.agent  —  the Kaizen RAG agent (LangGraph state machine).

A self-correcting "1 % better every run" loop that designs gf180 RF/mmWave
layouts without fine-tuning the model. Knowledge lives in three ChromaDB
collections (templates / theory / lessons); logic lives here.

    plan ─▶ retrieve ─▶ generate ─▶ test(DRC) ─▶ critic ─┬─(pass)─▶ summarize
                            ▲                             │
                            └──── kaizen_memory ◀─(fail, retries left)

The critic grades the layout against the real DRC result. On failure it writes
a problem→fix lesson into ``glayout_lessons_learned`` so the *next* run (and
future runs on similar prompts) retrieves the correction before generating —
in-context learning instead of SFT.
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict

# Per-thread event callback. LangGraph does not preserve non-schema keys (like a
# callback) across nodes, so we stash it thread-locally instead of in the state.
# The web app runs each agent.run() in its own thread → thread-local is correct.
_CB = threading.local()

from gelochip.kaizen import collections, config


# ── Shared state ──────────────────────────────────────────────────────────────
class KaizenState(TypedDict, total=False):
    query: str
    job_dir: str
    plan: str
    circuit: str
    ctx_templates: str
    ctx_theory: str
    ctx_lessons: str
    ctx_research: str
    research_docs: list
    extracted: str
    image_findings: str
    code: str
    attempt: int
    test: dict
    answer: str
    done: bool
    events: list


# ── LLM handle ────────────────────────────────────────────────────────────────
def get_llm(model: Optional[str] = None, temperature: Optional[float] = None,
            num_predict: Optional[int] = None):
    from langchain_ollama import ChatOllama

    # qwen3.5:9b supports up to 262k context. We default to a large-but-runnable
    # window; crank KAIZEN_NUM_CTX up to 262144 if you have the RAM/VRAM for the KV
    # cache (it gets slow + memory-heavy at the extreme). num_predict caps OUTPUT
    # length — that's what governs how long the generated code can be.
    # qwen3.5 is a *thinking* model: left on, it spends the entire num_predict
    # budget on hidden <think> tokens and returns EMPTY content (done_reason=
    # "length") — which is why the plan/code came back blank. We disable hidden
    # reasoning by default so the budget produces real output; set
    # KAIZEN_REASONING=1 to re-enable it (we still surface it as live "thinking").
    reasoning = os.getenv("KAIZEN_REASONING", "0") == "1"
    return ChatOllama(
        model=model or config.LLM_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        reasoning=reasoning,
        temperature=config.LLM_TEMPERATURE if temperature is None else temperature,
        num_ctx=int(os.getenv("KAIZEN_NUM_CTX", "32768")),
        num_predict=num_predict if num_predict is not None
                    else int(os.getenv("KAIZEN_GEN_TOKENS", "8192")),
        repeat_penalty=1.3,       # kill the degenerate "Create the … component" loop
        repeat_last_n=320,
        top_p=0.9,
        top_k=40,
    )


def get_vlm(num_predict: int = 600):
    """Vision-language model handle (Ollama) used by the Extractor to read
    schematics/layout figures. Separate from the reasoning LLM so the main model
    needn't be multimodal."""
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=config.VLM_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=0.1,
        num_ctx=8192,
        num_predict=num_predict,
    )


def _chunk_parts(chunk) -> tuple[str, str]:
    """Return (content, reasoning) for an Ollama stream chunk. Thinking models
    put their <think> stream in additional_kwargs['reasoning_content']."""
    content = chunk.content if hasattr(chunk, "content") else str(chunk)
    reasoning = ""
    ak = getattr(chunk, "additional_kwargs", None) or {}
    if isinstance(ak, dict):
        reasoning = ak.get("reasoning_content") or ak.get("reasoning") or ""
    return content or "", reasoning or ""


def _looks_runaway(text: str, tail_lines: int = 14, max_unique: int = 3) -> bool:
    """Detect a local model degenerating into a repetition loop (e.g. the same
    one/two comment lines emitted forever). Looks at the last `tail_lines`
    non-blank lines: if they collapse to <= max_unique distinct lines, it's a
    runaway. Cheap enough to call on every streamed chunk."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < tail_lines:
        return False
    tail = lines[-tail_lines:]
    # ignore trivially short lines (closing brackets etc.) when judging variety
    meaningful = [ln for ln in tail if len(ln) > 8]
    if len(meaningful) < tail_lines - 2:
        return False
    return len(set(meaningful)) <= max_unique


def _postprocess_code(text: str, max_period: int = 6, keep: int = 2) -> str:
    """Clean a generated code blob: collapse runaway repetition and drop trailing
    junk after the final top-level ``component =`` assignment. Handles both
    single-line runs and multi-line CYCLES (the model's "A line / B line / A / B…"
    degeneration), keeping at most `keep` copies of any repeating block. Conservative
    — real glayout code almost never repeats a non-trivial block 3+ times, so this
    only removes degeneration, never legitimate structure."""
    out: list[str] = []
    for ln in text.splitlines():
        out.append(ln)
        # if the tail now ends in > keep repetitions of a period-p block, drop the
        # excess copy. Check small periods first so single-line runs collapse too.
        for p in range(1, max_period + 1):
            if len(out) < p * (keep + 1):
                continue
            block = out[-p:]
            if not any(b.strip() for b in block):
                continue  # don't collapse blank-line blocks
            reps, j = 1, len(out) - p
            while j - p >= 0 and out[j - p:j] == block:
                reps += 1
                j -= p
            if reps > keep:
                del out[-p:]
                break
    # 2) trim trailing junk: keep through the LAST top-level `component =` statement;
    # anything after that which is only comments/blanks/repeats is degeneration.
    last_comp = max((i for i, ln in enumerate(out)
                     if re.match(r"\s*component\s*=", ln)), default=None)
    if last_comp is not None:
        tail = out[last_comp + 1:]
        if all((not t.strip()) or t.lstrip().startswith("#") for t in tail):
            out = out[:last_comp + 1]
    return "\n".join(out).strip()


def _text(resp) -> str:
    return resp.content if hasattr(resp, "content") else str(resp)


def _stream_text(state, node: str, llm, prompt: str, label: str = "thinking") -> str:
    """Stream an LLM call, emitting live `thinking` events (chatty), return full text."""
    parts: list[str] = []
    reason: list[str] = []
    last = 0
    try:
        # Heartbeat covers the silent model-load before the first token streams.
        with _Heartbeat(state, node, label):
            for chunk in llm.stream(prompt):
                c, r = _chunk_parts(chunk)
                if c:
                    parts.append(c)
                if r:
                    reason.append(r)
                cur = "".join(parts)
                # show the live answer if present, else the model's reasoning
                shown = cur or "".join(reason)
                if len(shown) - last >= 80:      # throttle: ~every 80 chars (chatty)
                    last = len(shown)
                    _emit(state, node, f"{label}… ({len(shown)} chars)", thinking=shown, streaming=True)
    except Exception:
        parts = [_text(llm.invoke(prompt))]
    out = "".join(parts)
    return out or "".join(reason)   # fall back to reasoning if content was empty


def _retrieve(collection: str, query: str, k: int, **flt) -> list:
    store = collections.get_vectorstore(collection)
    kwargs = {"k": k}
    if flt:
        kwargs["filter"] = flt
    try:
        return store.similarity_search(query, **kwargs)
    except Exception:
        return []


def _fmt(docs: list, limit: int = 3500) -> str:
    # large context window → include full retrieved examples (not truncated stubs)
    return "\n\n---\n".join(d.page_content[:limit] for d in docs) or "(none retrieved)"


# ── Prompts ───────────────────────────────────────────────────────────────────
# A COMPLETE, VERIFIED-clean reference (full 5-device amplifier) the model imitates.
_GL_REFERENCE = '''from glayout.pdk.gf180_mapped import gf180_mapped_pdk as PDK
from glayout.primitives.fet import nmos, pmos
from glayout.routing.c_route import c_route
from glayout.routing.straight_route import straight_route
from glayout.util.comp_utils import evaluate_bbox
from gdsfactory.component import Component

# Complete single-stage amplifier: NMOS differential/CS input, PMOS mirror load,
# NMOS tail. Every device is placed AND fully wired, and every external net is
# exposed as a port. Devices are spaced generously so routing stays DRC-clean.
top = Component(name="AMP")
m1 = nmos(PDK, width=4, fingers=2, length=0.5)   # input device 1 (g=VIP, s=VTAIL, d=VX)
m2 = nmos(PDK, width=4, fingers=2, length=0.5)   # input device 2 (g=VIM, s=VTAIL, d=VOUT)
m3 = pmos(PDK, width=8, fingers=2, length=0.5)   # load mirror ref  (d=VX,   g=VX, s=VDD)
m4 = pmos(PDK, width=8, fingers=2, length=0.5)   # load mirror copy (d=VOUT, g=VX, s=VDD)
m5 = nmos(PDK, width=8, fingers=2, length=0.5)   # tail current source (g=VBIAS, d=VTAIL, s=VSS)
r1 = top << m1; r2 = top << m2; r3 = top << m3; r4 = top << m4; r5 = top << m5
bw, bh = evaluate_bbox(m1)
r2.movex(bw + 8.0)                                # diff pair side by side
r3.movey(bh + 11.0); r4.movex(bw + 8.0); r4.movey(bh + 11.0)   # PMOS load on top
r5.movex((bw + 8.0) / 2); r5.movey(-(bh + 11.0))  # tail below, centred
# wire every connection (same-orientation c_route / vertical straight_route)
top << straight_route(PDK, r1.ports["multiplier_0_drain_N"], r3.ports["multiplier_0_drain_S"])  # VX
top << straight_route(PDK, r2.ports["multiplier_0_drain_N"], r4.ports["multiplier_0_drain_S"])  # VOUT
top << c_route(PDK, r3.ports["multiplier_0_gate_N"], r4.ports["multiplier_0_gate_N"])           # load gates
top << straight_route(PDK, r3.ports["multiplier_0_drain_W"], r3.ports["multiplier_0_gate_W"])   # mirror diode
top << c_route(PDK, r1.ports["multiplier_0_source_S"], r2.ports["multiplier_0_source_S"])       # VTAIL
top << straight_route(PDK, r5.ports["multiplier_0_drain_N"], r1.ports["multiplier_0_source_S"]) # tail->VTAIL
for i, r in enumerate((r1, r2, r3, r4, r5)):
    top.add_ports(r.get_ports_list(), prefix=f"M{i+1}_")        # expose every device's ports
component = top'''

_GL_API_HINT = f"""\
You output PURE glayout Python — ONLY a single ```python code block, no prose,
NO repetition. Hard rules (follow EXACTLY — wrong API = instant failure):

1. Use ONLY these real imports (NEVER `from glayout import nmos, Component` — that
   API does NOT exist):
       from glayout.pdk.gf180_mapped import gf180_mapped_pdk
       from glayout.primitives.fet import nmos, pmos
       from glayout.routing.c_route import c_route
       from glayout.routing.straight_route import straight_route
       from glayout.util.comp_utils import evaluate_bbox
       from gdsfactory.component import Component
2. `nmos`/`pmos` take (pdk, width=, fingers=, length=) and are already DRC-clean.
3. Build into a gdsfactory Component; bind it to `component` on the LAST line.
4. Route ONLY with c_route (same-orientation ports, e.g. gate_N↔gate_N) and
   straight_route (vertical stacks, drain_N↔source_S). Place devices with a
   generous gap via evaluate_bbox + a few µm so routing stays DRC-clean.
5. gf180 only. No ngspice. Write each line ONCE — do not repeat blocks.
6. IMPLEMENT THE COMPLETE CIRCUIT from the plan: EVERY transistor (input, cascode,
   load, mirror, tail/bias), EVERY gate/drain/source connection, and expose EVERY
   external net as a port. Do NOT output a 2-device stub — match the reference's
   completeness (5+ devices, all wired). Longer, complete code is expected.

Adapt the closest VERIFIED example below to the request. Reference pattern:
```python
{_GL_REFERENCE}
```
"""


# ── Nodes ─────────────────────────────────────────────────────────────────────
class KaizenCancelled(Exception):
    """Raised to abort a run cooperatively at the next streamed event."""


def _emit(state: KaizenState, node: str, msg: str, **extra) -> None:
    # Cooperative cancellation: abort promptly at the next event boundary.
    chk = getattr(_CB, "cancel", None)
    if chk and chk():
        raise KaizenCancelled()
    ev = {"node": node, "msg": msg, **extra}
    state.setdefault("events", []).append(ev)
    cb = getattr(_CB, "on_event", None) or state.get("_on_event")
    if cb:
        cb(ev)


class _Heartbeat:
    """Keep the event log alive during long *blocking* calls (LLM model-load,
    Magic DRC, web research) that would otherwise emit nothing for 30-90 s.

    Runs a daemon thread that ticks every few seconds with elapsed time. The
    event callback is thread-local (LangGraph quirk), so we capture it on the
    main thread and hand it to the ticker explicitly.
    """

    def __init__(self, state: "KaizenState", node: str, label: str, every: float = 3.0):
        self.state, self.node, self.label, self.every = state, node, label, every
        self.cb = getattr(_CB, "on_event", None) or state.get("_on_event")
        self._stop = threading.Event()
        self._t: Optional[threading.Thread] = None
        self._t0 = time.time()

    def __enter__(self) -> "_Heartbeat":
        if self.cb:
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            el = int(time.time() - self._t0)
            ev = {"node": self.node, "msg": f"{self.label}… working ({el}s)", "heartbeat": True}
            try:
                self.state.setdefault("events", []).append(ev)
                self.cb(ev)
            except Exception:
                return

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._t:
            self._t.join(timeout=0.2)


def node_plan(state: KaizenState) -> KaizenState:
    _emit(state, "plan", "planning the circuit… (first call may load the LLM, ~30–90 s)", start=True)
    llm = get_llm(num_predict=900)
    prompt = (
        "You are a senior analog/RF IC designer planning a gf180 layout. Produce a "
        "DETAILED, structured plan the layout-coder will follow. Cover:\n"
        "1. CIRCUIT TYPE (1-3 words).\n"
        "2. TOPOLOGY: every transistor (M1, M2, …) with role (input/cascode/load/"
        "tail/mirror) and its gate/drain/source net.\n"
        "3. DEVICE SIZING: W, L, fingers for each device, with a one-line reason tied "
        "to the spec (gain, bandwidth/frequency, bias current).\n"
        "4. NODES/PORTS: list the external pins (inputs, output, bias, VDD, VSS).\n"
        "5. PLACEMENT & ROUTING: how devices are arranged (rows / vertical cascode "
        "stack) and which ports connect (c_route same-orientation; straight_route for "
        "vertical drain→source stacks), keeping generous spacing for DRC.\n"
        "6. DRC/verification notes (guard ring / substrate ties, spacing).\n"
        "Be specific and concrete, not generic.\n\nRequest: " + state["query"]
    )
    plan = _stream_text(state, "plan", llm, prompt, label="planning")
    circuit = collections._guess_circuit(plan + " " + state["query"])
    _emit(state, "plan", plan, circuit=circuit)
    return {"plan": plan, "circuit": circuit, "attempt": state.get("attempt", 0)}


def _job_id(state: KaizenState) -> str:
    return Path(state.get("job_dir", "session")).name


def node_research(state: KaizenState) -> KaizenState:
    """Researcher + Extractor: find external papers/web/github, build a TEMP RAG."""
    from gelochip.kaizen import researcher

    _emit(state, "research", "searching arXiv / web / GitHub (crawl4ai)…", start=True)
    with _Heartbeat(state, "research", "researching the web"):
        docs = researcher.research(state["query"] + " gf180 RF analog IC layout")
        if docs:
            _emit(state, "research", f"got {len(docs)} sources → building a temporary RAG index…")
            researcher.build_temp_rag(docs, _job_id(state))
    srcs = {d["source"] for d in docs}
    # surface the extracted info so the user can verify it BEFORE generation
    sources = [{"title": (d.get("title") or "")[:140], "source": d.get("source", ""),
                "url": d.get("url", ""), "snippet": (d.get("text") or "")[:300]} for d in docs]
    _emit(state, "research",
          f"found {len(docs)} sources ({', '.join(sorted(srcs)) or 'none — offline?'}) → temp RAG",
          sources=sources)
    return {"research_docs": docs}


def node_retrieve(state: KaizenState) -> KaizenState:
    from gelochip.kaizen import researcher
    _emit(state, "retrieve", "retrieving from the 3 collections + research…", start=True)
    q = state["query"] + "\n" + state.get("plan", "")
    # Prefer the FULL verified clean-circuit code (correct API) over partial
    # operation snippets; fall back to general templates to fill.
    clean = _retrieve(config.COLL_TEMPLATES, q, 2, doc_type="clean_circuit")
    seen = {d.page_content[:60] for d in clean}
    extra = [d for d in _retrieve(config.COLL_TEMPLATES, q, config.TOP_K_TEMPLATES)
             if d.page_content[:60] not in seen]
    tmpl = clean + extra[:2]
    theory = _retrieve(config.COLL_THEORY, q, config.TOP_K_THEORY)
    lessons = _retrieve(config.COLL_LESSONS, q, config.TOP_K_LESSONS)
    research = researcher.query_temp_rag(_job_id(state), q, k=3) if state.get("research_docs") else []
    # surface the retrieved grounding so the user can verify it before generation
    retrieved = {
        "templates": [{"label": d.metadata.get("circuit", "template"),
                       "snippet": d.page_content[:220]} for d in tmpl],
        "theory": [{"label": d.metadata.get("source", "theory"),
                    "snippet": d.page_content[:200]} for d in theory],
        "research": [{"label": d.metadata.get("source", "research"),
                      "snippet": d.page_content[:200]} for d in research],
    }
    _emit(state, "retrieve",
          f"templates={len(tmpl)} theory={len(theory)} lessons={len(lessons)} research={len(research)}",
          retrieved=retrieved)
    # Full clean code (the thing to copy) stays long; secondary context is kept
    # short so the prompt stays fast to process.
    return {"ctx_templates": _fmt(tmpl, 3500), "ctx_theory": _fmt(theory, 900),
            "ctx_lessons": _fmt(lessons, 900), "ctx_research": _fmt(research, 900)}


def _fetch_image_b64(url: str, timeout: float = 8.0) -> Optional[tuple[str, str]]:
    """Download an image → (mime_type, base64). None on failure / non-image."""
    import base64

    import httpx
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (gelochip-extractor)"})
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "image/png").split(";")[0].strip()
        if "image" not in ct or not r.content:
            return None
        return ct, base64.b64encode(r.content).decode()
    except Exception:
        return None


def _local_image_b64(path: str) -> Optional[tuple[str, str]]:
    """Read a local image file → (mime_type, base64). None on failure."""
    import base64
    try:
        data = open(path, "rb").read()
        if not data:
            return None
        mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        return mime, base64.b64encode(data).decode()
    except Exception:
        return None


def _vision_review_layout(state: KaizenState, png_path: str, drc_text: str) -> str:
    """Vision-in-the-loop: show the VLM the *rendered GDS* of the failed attempt
    alongside its DRC errors, and ask what is visually wrong and how to fix the
    placement/routing. Returns '' if no VLM / no image (purely additive)."""
    from langchain_core.messages import HumanMessage
    fetched = _local_image_b64(png_path) if png_path else None
    if not fetched:
        return ""
    try:
        vlm = get_vlm()
    except Exception:
        return ""
    ct, b64 = fetched
    try:
        with _Heartbeat(state, "generate", "looking at the rendered layout"):
            msg = HumanMessage(content=[
                {"type": "text", "text": (
                    "You are an analog IC layout engineer. This image is the RENDERED "
                    "GDS of a layout your code just produced, and it FAILED DRC. Look at "
                    "the actual geometry and, using the DRC errors below, say concretely "
                    "WHERE the problem is (which devices/routes overlap, are too close, "
                    "too narrow, or mis-aligned) and HOW to fix it in glayout terms "
                    "(move a device, widen/shift a route, add spacing, change a via). "
                    "Be terse — bullet points tied to what you SEE.\n\n"
                    f"DRC errors:\n{drc_text[:800]}")},
                {"type": "image_url", "image_url": f"data:{ct};base64,{b64}"},
            ])
            txt = _text(vlm.invoke([msg])).strip()
        if txt:
            _emit(state, "generate", "vision review of the failed layout ✓", streaming=True)
        return txt
    except Exception:
        return ""


def _extract_from_images(state: KaizenState, urls: list[str]) -> str:
    """Vision pass: ask the VLM to mine concrete design facts out of each figure
    (schematic / layout / plot). Fully best-effort — returns '' if no VLM, the
    images can't be fetched, or anything goes wrong."""
    from langchain_core.messages import HumanMessage

    try:
        vlm = get_vlm()
    except Exception:
        return ""
    findings: list[str] = []
    with _Heartbeat(state, "extract", "reading schematics/figures with the vision model"):
        for i, u in enumerate(urls, 1):
            fetched = _fetch_image_b64(u)
            if not fetched:
                continue
            ct, b64 = fetched
            try:
                msg = HumanMessage(content=[
                    {"type": "text", "text": (
                        "You are an analog/RF IC layout expert. This image is a figure "
                        "from a paper or repo — a schematic, a chip layout, or a plot. "
                        "Extract ONLY concrete, design-useful facts: circuit topology, "
                        "transistor roles & count, how devices connect, any device "
                        "sizing / W-L / ratios / bias currents, and layout or floorplan "
                        "cues (rows, mirroring, guard rings). If it is NOT a circuit "
                        "figure, reply exactly 'not relevant'. Be terse — bullet facts.")},
                    {"type": "image_url", "image_url": f"data:{ct};base64,{b64}"},
                ])
                txt = _text(vlm.invoke([msg])).strip()
            except Exception:
                continue
            if txt and "not relevant" not in txt.lower()[:40]:
                findings.append(f"[figure {i}] {txt}")
                _emit(state, "extract", f"read figure {i}/{len(urls)} ✓", streaming=True)
    return "\n\n".join(findings)


def node_extract(state: KaizenState) -> KaizenState:
    """Extractor agent: mine the retrieved CODE, THEORY, RESEARCH text and the
    found IMAGES into one concrete DESIGN SPECIFICATION that upgrades the plan
    before generation. This is the step that turns scattered grounding into a
    precise, buildable spec — and it reads figures, not just text."""
    _emit(state, "extract", "extracting facts from knowledge, code & figures…", start=True)

    # 1. Vision pass over schematics/layouts the researcher surfaced.
    img_urls = [d["url"] for d in state.get("research_docs", [])
                if d.get("source") == "image" and d.get("url")][:config.VLM_MAX_IMAGES]
    image_findings = _extract_from_images(state, img_urls) if img_urls else ""

    # 2. Text consolidation: fuse every source into a single actionable spec.
    llm = get_llm(num_predict=1200, temperature=0.2)
    prompt = (
        "You are a senior analog/RF IC designer acting as an INFORMATION EXTRACTOR. "
        "From the grounding below, distil ONE concrete DESIGN SPECIFICATION the "
        "layout-coder will follow. Mine every useful fact from the retrieved glayout "
        "CODE (exact imports, device calls, real port-name patterns, routing idioms), "
        "the RF THEORY, the RESEARCHED references, the VISION findings from figures, "
        "and the original plan. Resolve conflicts, fill gaps, stay specific — no fluff.\n\n"
        "Output these sections, terse and concrete:\n"
        "A. CONFIRMED TOPOLOGY — every transistor (M1, M2, …), its role, and its "
        "gate/drain/source net.\n"
        "B. SIZING — W, L, fingers per device with a one-line reason (spec/theory/figure).\n"
        "C. PORTS / NETS — the external pins (inputs, output, bias, VDD, VSS).\n"
        "D. GLAYOUT API FACTS — exact imports, the nmos/pmos signature, the real "
        "port-name patterns and the c_route/straight_route idioms seen in the code.\n"
        "E. PLACEMENT & ROUTING — rows vs vertical stacks, spacing, which ports connect.\n"
        "F. PITFALLS — concrete things to avoid, drawn from the lessons and figures.\n\n"
        f"# Design request\n{state['query']}\n\n"
        f"# Original plan\n{state.get('plan','')}\n\n"
        f"# Retrieved glayout code / templates\n{state.get('ctx_templates','')}\n\n"
        f"# RF/mmWave theory\n{state.get('ctx_theory','')}\n\n"
        f"# Researched references\n{state.get('ctx_research','(none)')}\n\n"
        f"# Lessons learned (past mistakes)\n{state.get('ctx_lessons','')}\n\n"
        f"# Vision findings from figures/schematics\n{image_findings or '(no figures read)'}\n\n"
        "Now output the consolidated DESIGN SPECIFICATION:"
    )
    spec = _stream_text(state, "extract", llm, prompt, label="extracting")
    n_fig = image_findings.count("[figure")
    _emit(state, "extract",
          f"design spec ready ({len(spec)} chars" +
          (f", {n_fig} figure(s) read)" if n_fig else ")"),
          extracted=spec, image_findings=image_findings)
    return {"extracted": spec, "image_findings": image_findings}


def node_generate(state: KaizenState) -> KaizenState:
    # RAG (not SFT): generate with the main qwen3.5:9b agent, grounded on the
    # retrieved glayout templates. Set KAIZEN_USE_CODER=1 to use the SFT coder.
    use_coder = os.getenv("KAIZEN_USE_CODER") == "1"
    attempt_n = state.get("attempt", 0) + 1
    _emit(state, "generate", f"generating glayout code with the LLM (attempt {attempt_n})…", start=True)
    # low temperature → deterministic code; large output budget (KAIZEN_GEN_TOKENS,
    # default 8192) so complex multi-device circuits aren't truncated; repeat_penalty
    # prevents runaway repetition.
    llm = get_llm(model=config.CODER_MODEL if use_coder else None, temperature=0.1)
    feedback = ""
    test = state.get("test")
    if test and not test.get("passed"):
        drc_text = str(test.get("error") or test.get("drc"))
        feedback = (
            "\n\nThe PREVIOUS attempt FAILED. Fix it.\n"
            f"Failure stage: {test.get('stage')}\n"
            f"Error / DRC: {drc_text}\n"
        )
        # Vision-in-the-loop: let the model SEE the rendered GDS of the failed
        # attempt, not just read the error text, and fold the visual review in.
        review = _vision_review_layout(state, test.get("png_path"), drc_text)
        if review:
            feedback += (
                "\nVISUAL REVIEW of the rendered layout above (what the error looks "
                f"like on the actual geometry):\n{review}\n"
            )
    prompt = (
        f"{_GL_API_HINT}\n\n"
        f"# Design request\n{state['query']}\n\n"
        f"# Plan\n{state.get('plan','')}\n\n"
        f"# Consolidated design spec — FOLLOW THIS (extracted from code, theory & figures)\n"
        f"{state.get('extracted','(none)')}\n\n"
        f"# Retrieved glayout templates (reuse the closest one)\n{state['ctx_templates']}\n\n"
        f"# Relevant RF/mmWave theory\n{state['ctx_theory']}\n\n"
        f"# Researched references (papers/web/github)\n{state.get('ctx_research','(none)')}\n\n"
        f"# Lessons learned — avoid these past mistakes\n{state['ctx_lessons']}"
        f"{feedback}\n\nNow output the glayout code:"
    )
    attempt = state.get("attempt", 0) + 1
    # Stream the code so the UI shows it being written live (throttled emits).
    parts: list[str] = []
    reason: list[str] = []
    last = 0
    try:
        # Heartbeat covers the silent model-load before the first code token.
        with _Heartbeat(state, "generate", "the coder is warming up"):
            for chunk in llm.stream(prompt):
                c, r = _chunk_parts(chunk)
                if c:
                    parts.append(c)
                if r:
                    reason.append(r)
                cur = "".join(parts)
                if cur and len(cur) - last >= 150:
                    last = len(cur)
                    # Abort a degenerate repetition loop instead of burning the
                    # whole token budget echoing the same line (the "writing
                    # code… (15261 chars)" runaway). The code so far is salvaged
                    # and cleaned below.
                    if _looks_runaway(cur):
                        _emit(state, "generate",
                              "stopped a repetition loop — trimming the dead tail",
                              streaming=True, version=attempt)
                        break
                    _emit(state, "generate", f"writing code… ({len(cur)} chars)",
                          code=cur, streaming=True, version=attempt)
    except Exception:
        # fall back to a single blocking call if streaming is unavailable
        parts = [_text(llm.invoke(prompt))]
    code = _postprocess_code("".join(parts) or "".join(reason))
    _emit(state, "generate", f"attempt {attempt}: {len(code)} chars",
          code=code, version=attempt)
    return {"code": code, "attempt": attempt}


def node_test(state: KaizenState) -> KaizenState:
    from gelochip.kaizen.executor import run_layout_code

    _emit(state, "test", "building GDS → Magic DRC → SPICE/AC/transient testbench…", start=True)
    job = state.get("job_dir") or str(config.OUTPUT_DIR / "session")
    with _Heartbeat(state, "test", "building + DRC + simulating"):
        res = run_layout_code(state["code"], job, name=f"kaizen_{state.get('attempt',1)}",
                              run_testbench=True)
    drc = res.get("drc", {})
    tb = res.get("testbench", {})
    summary = (f"stage={res['stage']} ok={res['ok']} passed={res['passed']} "
               f"drc_errors={drc.get('total_errors')} tb_passed={tb.get('passed')}")
    _emit(state, "test", summary, png_path=res.get("png_path"),
          gds_path=res.get("gds_path"), spice_path=res.get("spice_path"),
          ac_plot=tb.get("ac_plot"), tran_plot=tb.get("tran_plot"),
          passed=res["passed"])
    return {"test": res}


def node_kaizen_memory(state: KaizenState) -> KaizenState:
    """On failure, distil a problem→fix lesson and store it for next time."""
    _emit(state, "kaizen_memory", "DRC failed — distilling an error→fix lesson…", start=True)
    test = state["test"]
    llm = get_llm()
    prompt = (
        "A glayout layout attempt failed. In <=3 sentences, state the ROOT CAUSE and "
        "the concrete FIX for next time.\n"
        f"Stage: {test.get('stage')}\nError/DRC: {test.get('error') or test.get('drc')}\n"
        f"Code:\n{state.get('code','')[:1500]}"
    )
    fix = _text(llm.invoke(prompt))
    collections.add_lesson(
        scenario=state["query"][:300],
        error=str(test.get("error") or test.get("drc"))[:600],
        root_cause=fix,
        fix=fix,
        circuit=state.get("circuit", "generic"),
        status="historical_error",
    )
    _emit(state, "kaizen_memory", "error→fix lesson stored → error_feedback")
    return {}


def node_summarize(state: KaizenState) -> KaizenState:
    from gelochip.kaizen import researcher
    _emit(state, "persist", "promoting verified knowledge to ChromaDB…", start=True)
    test = state.get("test", {})
    drc = test.get("drc", {})
    passed = bool(test.get("passed"))
    verdict = "✅ DRC clean" if passed else "❌ not clean"
    if drc.get("skipped"):
        verdict = "⚠️ DRC skipped (tools unavailable)"

    # On success, promote temp research + verified code into permanent ChromaDB.
    if passed:
        try:
            added = researcher.persist_on_success(
                _job_id(state), state["query"], state.get("code", ""),
                state.get("circuit", "generic"), state.get("research_docs", []))
            _emit(state, "persist",
                  f"promoted → rf_theory +{added['theory']}, glayout_knowledge +{added['knowledge']}")
        except Exception as e:
            _emit(state, "persist", f"persist skipped ({e})")
    else:
        researcher.drop_temp_rag(_job_id(state))   # discard temp knowledge on failure

    answer = (
        f"{verdict} after {state.get('attempt',0)} attempt(s).\n"
        f"Circuit: {state.get('circuit','?')}\n"
        f"GDS: {test.get('gds_path') or '—'}\n"
        f"DRC errors: {drc.get('total_errors', '—')}\n"
    )
    # Persist the human-readable artifacts into the project's text/ and link/ folders.
    try:
        import json as _json
        jd = Path(state.get("job_dir", ""))
        if jd.name:
            (jd / "text").mkdir(parents=True, exist_ok=True)
            (jd / "link").mkdir(parents=True, exist_ok=True)
            (jd / "text" / "summary.md").write_text(
                f"# {state.get('circuit','design')}\n\n{answer}\n\n"
                f"## Request\n{state['query']}\n\n## Plan\n{state.get('plan','')}\n")
            drc_rep = drc.get("report") or drc.get("error") or str(drc.get("error_details", ""))
            if drc_rep:
                (jd / "text" / "drc_report.txt").write_text(str(drc_rep))
            links = [{"url": d.get("url"), "source": d.get("source"), "title": d.get("title")}
                     for d in state.get("research_docs", []) if d.get("url")]
            if links:
                (jd / "link" / "links.json").write_text(_json.dumps(links, indent=2))
    except Exception:
        pass
    _emit(state, "summarize", answer)
    return {"answer": answer, "done": True}


# ── Routing ───────────────────────────────────────────────────────────────────
def _route_after_test(state: KaizenState) -> str:
    test = state.get("test", {})
    if test.get("passed"):
        return "summarize"
    if state.get("attempt", 0) >= config.MAX_KAIZEN_ITERS:
        return "summarize"
    return "kaizen_memory"


# ── Graph ─────────────────────────────────────────────────────────────────────
def build_graph():
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(KaizenState)
    g.add_node("plan", node_plan)
    g.add_node("research", node_research)
    g.add_node("retrieve", node_retrieve)
    g.add_node("extract", node_extract)
    g.add_node("generate", node_generate)
    g.add_node("test", node_test)
    g.add_node("kaizen_memory", node_kaizen_memory)
    g.add_node("summarize", node_summarize)

    g.add_edge(START, "plan")
    g.add_edge("plan", "research")
    g.add_edge("research", "retrieve")
    g.add_edge("retrieve", "extract")
    g.add_edge("extract", "generate")
    g.add_edge("generate", "test")
    g.add_conditional_edges("test", _route_after_test,
                            {"summarize": "summarize", "kaizen_memory": "kaizen_memory"})
    g.add_edge("kaizen_memory", "generate")   # re-generate with the new lesson in context
    g.add_edge("summarize", END)
    return g.compile()


# ── Convenience runner ────────────────────────────────────────────────────────
def run(query: str, job_dir: Optional[str] = None,
        on_event: Optional[Callable[[dict], None]] = None,
        cancel: Optional[Callable[[], bool]] = None) -> KaizenState:
    """Run the full Kaizen loop once and return the final state.

    `cancel` is an optional predicate checked at each event boundary; when it
    returns True the run aborts cooperatively (KaizenCancelled), returning the
    partial state gathered so far.
    """
    config.ensure_dirs()
    graph = build_graph()
    state: KaizenState = {
        "query": query,
        "job_dir": job_dir or str(config.OUTPUT_DIR / "session"),
        "events": [],
    }
    _CB.on_event = on_event           # thread-local — survives across LangGraph nodes
    _CB.cancel = cancel
    try:
        final = graph.invoke(state, config={"recursion_limit": 50})
    except KaizenCancelled:
        state["answer"] = "⏹ cancelled by user"
        final = state
    finally:
        _CB.on_event = None
        _CB.cancel = None
    return final
