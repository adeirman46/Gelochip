"""Google Gemini (Vertex AI) backend for the PandaChip agent.

Authenticates with Application Default Credentials (ADC) — run
`gcloud auth application-default login` once — and speaks the same
message / tool-call dialect as the Ollama chat endpoint, so agent.py
switches backends purely on the model name (gemini-*). No Google SDK
required: the OAuth refresh and generateContent calls go through urllib.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ADC_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.path.expanduser(
    "~/.config/gcloud/application_default_credentials.json")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")

_token: dict = {}


def _adc() -> dict:
    try:
        return json.loads(Path(ADC_PATH).read_text())
    except FileNotFoundError:
        raise RuntimeError(
            f"Google ADC not found at {ADC_PATH}. Run: "
            "gcloud auth application-default login") from None


def project() -> str:
    return os.getenv("GOOGLE_CLOUD_PROJECT") or _adc().get("quota_project_id", "")


def _access_token() -> str:
    if _token and _token["expires"] > time.time():
        return _token["value"]
    adc = _adc()
    if adc.get("type") != "authorized_user":
        raise RuntimeError(f"Unsupported ADC type {adc.get('type')!r}; "
                           "expected authorized_user (gcloud user login)")
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": adc["client_id"],
        "client_secret": adc["client_secret"],
        "refresh_token": adc["refresh_token"],
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req, timeout=30) as resp:
        tok = json.loads(resp.read())
    _token.update(value=tok["access_token"],
                  expires=time.time() + float(tok.get("expires_in", 3600)) - 60)
    return _token["value"]


def _mime(b64: str) -> str:
    head = base64.b64decode(b64[:16])
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _contents(messages: list[dict]) -> tuple[str, list[dict]]:
    """Ollama-dialect messages -> (system text, Gemini contents)."""
    system = ""
    contents: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            system = m.get("content", "")
        elif role == "assistant":
            # Prefer the raw parts of the original Gemini turn: they carry
            # the thought signatures Gemini 3 requires back verbatim.
            parts = m.get("_gemini_parts")
            if not parts:
                parts = []
                if m.get("content"):
                    parts.append({"text": m["content"]})
                for call in m.get("tool_calls") or []:
                    fn = call.get("function", {})
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    parts.append({"functionCall": {"name": fn.get("name"),
                                                   "args": args}})
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            try:
                payload = json.loads(m.get("content") or "{}")
            except json.JSONDecodeError:
                payload = {"content": m.get("content", "")}
            if not isinstance(payload, dict):
                payload = {"content": payload}
            part = {"functionResponse": {"name": m.get("name", "tool"),
                                         "response": payload}}
            # Parallel calls: every response to one model turn must ride in
            # ONE user turn, or Vertex rejects the request with 400
            # "number of function response parts" mismatch.
            if contents and contents[-1]["role"] == "user" and all(
                    "functionResponse" in p for p in contents[-1]["parts"]):
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
        else:  # user
            parts = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            for b64 in m.get("images") or []:
                parts.append({"inlineData": {"mimeType": _mime(b64),
                                             "data": b64}})
            contents.append({"role": "user", "parts": parts or [{"text": " "}]})
    return system, contents


def _reply(data: dict) -> dict:
    cand = (data.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts") or []
    visible = [p for p in parts if not p.get("thought")]
    text = "".join(p.get("text", "") for p in visible)
    calls = [{"function": {"name": p["functionCall"].get("name"),
                           "arguments": p["functionCall"].get("args") or {}}}
             for p in visible if p.get("functionCall")]
    msg: dict = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = calls
        msg["_gemini_parts"] = visible
    return {"message": msg}


def chat(model: str, messages: list[dict], tools: list[dict] | None = None,
         temperature: float = 0.3) -> dict:
    proj = project()
    if not proj:
        raise RuntimeError("No Google Cloud project: set GOOGLE_CLOUD_PROJECT "
                           "or re-run gcloud auth application-default login")
    system, contents = _contents(messages)
    body: dict = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            # Thinking tokens share this budget on Gemini 3 previews, so it
            # sits above the Ollama num_predict default on purpose.
            "maxOutputTokens": int(os.getenv("PANDACHIP_GEMINI_MAX_TOKENS",
                                             "16384"))},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        body["tools"] = [{"functionDeclarations": [t["function"] for t in tools]}]
    url = (f"https://aiplatform.googleapis.com/v1/projects/{proj}"
           f"/locations/{LOCATION}/publishers/google/models/"
           f"{model}:generateContent")
    payload = json.dumps(body).encode()
    has_images = any("inlineData" in p for c in contents for p in c["parts"])
    last_error: Exception | None = None
    for attempt in range(6):
        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_access_token()}"})
        try:
            print(f"  [chat] waiting for {model} (Vertex AI)"
                  f"{' (with images)' if has_images else ''}...", flush=True)
            with urllib.request.urlopen(req, timeout=300) as resp:
                return _reply(json.loads(resp.read()))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read()).get("error", {}).get(
                    "message", "")[:300]
            except Exception:
                pass
            if exc.code in (429, 500, 503) and attempt < 5:
                delay = min(120.0, 5.0 * 2 ** attempt)
                print(f"  [gemini retry {attempt + 1}] {exc.code} {detail}; "
                      f"waiting {int(delay)}s", flush=True)
                time.sleep(delay)
                last_error = exc
                continue
            raise RuntimeError(
                f"Gemini request failed: {exc.code} {detail or exc.reason}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException,
                ConnectionError, OSError) as exc:
            # Covers RemoteDisconnected / connection reset / DNS blips: a
            # transient network hiccup must never abort a whole design run.
            last_error = exc
            print(f"  [gemini retry {attempt + 1}] {type(exc).__name__}: {exc}",
                  flush=True)
            time.sleep(5.0 * (attempt + 1))
    raise RuntimeError(f"Gemini chat failed after retries: {last_error}")
