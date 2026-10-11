"""AI review suggestions for a finished PandaChip run.

Usage:
    .venv/bin/python -m pandachip.suggest designs/<run-id>

Reads the run's task, outcome, schematic-quality report and transcript
tail, asks the run's own model (Ollama or Gemini via the agent.chat
dispatch) for concrete fixes, writes suggestions.json into the workspace
and prints it to stdout. The web UI shows these next to the Retry button
when a run needs review.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
from pathlib import Path

from .agent import DEFAULT_MODEL, chat
from .eda_tools import Workspace


def _context(root: Path) -> str:
    parts: list[str] = []
    for name, cap in (("task.md", 2000), ("outcome.json", 2000),
                      ("plan.md", 1500)):
        f = root / name
        if f.exists():
            parts.append(f"## {name}\n{f.read_text(errors='replace')[:cap]}")
    try:
        problems = Workspace(str(root)).wiring_report()
        if problems:
            parts.append("## Schematic quality problems\n"
                         + "\n".join(problems[:6]))
    except Exception:
        pass
    t = root / "transcript.json"
    if t.exists():
        try:
            tail = []
            for m in json.loads(t.read_text())[-12:]:
                calls = ",".join(c["function"]["name"]
                                 for c in m.get("tool_calls") or [])
                tail.append(f"[{m.get('role')}"
                            f"{' calls=' + calls if calls else ''}] "
                            f"{str(m.get('content', ''))[:400]}")
            parts.append("## Transcript tail\n" + "\n".join(tail))
        except Exception:
            pass
    return "\n\n".join(parts)


def suggest(workdir: str) -> dict:
    root = Path(workdir)
    model = DEFAULT_MODEL
    try:
        model = json.loads((root / "meta.json").read_text()).get(
            "model") or model
    except Exception:
        pass
    prompt = (
        "You are reviewing an analog IC design run that did not fully meet "
        "its spec. From the context below, give 2-4 concrete, actionable "
        "suggestions for the retry. Reply ONLY with a JSON array: "
        '[{"title": "...", "detail": "..."}]. Each detail under 60 words, '
        "engineering-specific (component values, nodes, exact tool steps) - "
        "no generic advice.\n\n" + _context(root))
    reply = chat(model, [{"role": "user", "content": prompt}],
                 use_tools=False)
    text = reply.get("message", {}).get("content", "")
    items: list[dict] = []
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            items = [{"title": str(i.get("title", ""))[:120],
                      "detail": str(i.get("detail", ""))[:500]}
                     for i in json.loads(m.group(0)) if isinstance(i, dict)]
        except json.JSONDecodeError:
            pass
    if not items:
        items = [{"title": "Review the run manually",
                  "detail": text[:400] or "The model returned no parseable "
                  "suggestions; check agent.log and outcome.json."}]
    data = {"model": model, "suggestions": items}
    (root / "suggestions.json").write_text(json.dumps(data, indent=1))
    return data


def main() -> None:
    # chat() prints progress lines; keep stdout pure JSON for the caller.
    with contextlib.redirect_stdout(sys.stderr):
        data = suggest(sys.argv[1])
    print(json.dumps(data))


if __name__ == "__main__":
    main()
