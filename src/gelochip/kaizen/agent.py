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
import threading
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
    return ChatOllama(
        model=model or config.LLM_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=config.LLM_TEMPERATURE if temperature is None else temperature,
        num_ctx=int(os.getenv("KAIZEN_NUM_CTX", "32768")),
        num_predict=num_predict if num_predict is not None
                    else int(os.getenv("KAIZEN_GEN_TOKENS", "8192")),
        repeat_penalty=1.3,       # kill the degenerate "Create the … component" loop
        repeat_last_n=320,
        top_p=0.9,
        top_k=40,
    )


def _text(resp) -> str:
    return resp.content if hasattr(resp, "content") else str(resp)


def _stream_text(state, node: str, llm, prompt: str, label: str = "thinking") -> str:
    """Stream an LLM call, emitting live `thinking` events (chatty), return full text."""
    parts: list[str] = []
    last = 0
    try:
        for chunk in llm.stream(prompt):
            parts.append(chunk.content if hasattr(chunk, "content") else str(chunk))
            cur = "".join(parts)
            if len(cur) - last >= 120:           # throttle: ~every 120 chars
                last = len(cur)
                _emit(state, node, f"{label}… ({len(cur)} chars)", thinking=cur, streaming=True)
    except Exception:
        parts = [_text(llm.invoke(prompt))]
    return "".join(parts)


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
    docs = researcher.research(state["query"] + " gf180 RF analog IC layout")
    if docs:
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
        feedback = (
            "\n\nThe PREVIOUS attempt FAILED. Fix it.\n"
            f"Failure stage: {test.get('stage')}\n"
            f"Error / DRC: {test.get('error') or test.get('drc')}\n"
        )
    prompt = (
        f"{_GL_API_HINT}\n\n"
        f"# Design request\n{state['query']}\n\n"
        f"# Plan\n{state.get('plan','')}\n\n"
        f"# Retrieved glayout templates (reuse the closest one)\n{state['ctx_templates']}\n\n"
        f"# Relevant RF/mmWave theory\n{state['ctx_theory']}\n\n"
        f"# Researched references (papers/web/github)\n{state.get('ctx_research','(none)')}\n\n"
        f"# Lessons learned — avoid these past mistakes\n{state['ctx_lessons']}"
        f"{feedback}\n\nNow output the glayout code:"
    )
    attempt = state.get("attempt", 0) + 1
    # Stream the code so the UI shows it being written live (throttled emits).
    parts: list[str] = []
    last = 0
    try:
        for chunk in llm.stream(prompt):
            parts.append(chunk.content if hasattr(chunk, "content") else str(chunk))
            cur = "".join(parts)
            if len(cur) - last >= 250:
                last = len(cur)
                _emit(state, "generate", f"writing code… ({len(cur)} chars)",
                      code=cur, streaming=True, version=attempt)
    except Exception:
        # fall back to a single blocking call if streaming is unavailable
        parts = [_text(llm.invoke(prompt))]
    code = "".join(parts)
    _emit(state, "generate", f"attempt {attempt}: {len(code)} chars",
          code=code, version=attempt)
    return {"code": code, "attempt": attempt}


def node_test(state: KaizenState) -> KaizenState:
    from gelochip.kaizen.executor import run_layout_code

    _emit(state, "test", "building GDS → Magic DRC → SPICE/AC/transient testbench…", start=True)
    job = state.get("job_dir") or str(config.OUTPUT_DIR / "session")
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
    g.add_node("generate", node_generate)
    g.add_node("test", node_test)
    g.add_node("kaizen_memory", node_kaizen_memory)
    g.add_node("summarize", node_summarize)

    g.add_edge(START, "plan")
    g.add_edge("plan", "research")
    g.add_edge("research", "retrieve")
    g.add_edge("retrieve", "generate")
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
