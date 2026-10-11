"""
Central LLM / embeddings factory for AnoaChip.

Everything in the app gets its chat model and embeddings from here, so the
provider can be switched with a single environment variable instead of editing
code. The DEFAULT is a fully-local setup: Ollama for chat (e.g. qwen3.5:9b) and
local sentence-transformers for embeddings.

Configure via .env (see .env.example):

    LLM_PROVIDER        ollama | google          (default: ollama)
    OLLAMA_MODEL        e.g. qwen3.5:9b
    OLLAMA_BASE_URL     default http://localhost:11434
    GOOGLE_API_KEY      required when LLM_PROVIDER=google
    GOOGLE_MODEL        default gemini-2.5-pro

    EMBEDDINGS_PROVIDER huggingface | ollama | google   (default: huggingface)
    EMBEDDING_MODEL     default all-MiniLM-L6-v2
"""

from __future__ import annotations

import os
import functools

from dotenv import load_dotenv

# Load .env from the nearest parent directory so it works no matter which
# tool sub-directory Streamlit is launched from.
load_dotenv()


# Per-run context-window override (set by the pipeline from the chat parameter's slider).
# When None, get_chat_model falls back to OLLAMA_NUM_CTX. Process-global because the local
# app serves one user; the most recent run's value wins.
_NUM_CTX_OVERRIDE: "int | None" = None


def set_num_ctx(n) -> None:
    """Set the Ollama context window (num_ctx) used by every subsequent get_chat_model call,
    overriding OLLAMA_NUM_CTX. Pass a falsy value to clear the override."""
    global _NUM_CTX_OVERRIDE
    try:
        _NUM_CTX_OVERRIDE = int(n) if n else None
    except (TypeError, ValueError):
        _NUM_CTX_OVERRIDE = None


def _default_num_ctx() -> int:
    return _NUM_CTX_OVERRIDE or int(os.getenv("OLLAMA_NUM_CTX", "32768"))


# Per-run chat-model override (set by the pipeline from the chat's model picker). When None,
# get_chat_model falls back to OLLAMA_MODEL/.env. Process-global because the local app serves
# one user; the most recent run's choice wins. Lets the user run whatever they've pulled into
# Ollama (qwen3.5:9b, ornith:9b, glm-5.2, …) WITHOUT editing .env or restarting.
_MODEL_OVERRIDE: "str | None" = None


# Below this on-disk size (bytes) an Ollama entry is a "cloud" stub, not real local weights:
# the `*:cloud` models (glm-5.2:cloud, qwen3-coder:480b-cloud, …) are a few hundred bytes that
# proxy inference to Ollama's servers. No real local chat model is anywhere near this small.
_CLOUD_STUB_MAX_BYTES = 50 * 1024 * 1024


def is_cloud_model(name: str, size: int = 0, parameter_size: str = "") -> bool:
    """True for an Ollama 'cloud' model — one that runs on Ollama's servers, NOT locally.
    AnoaChip is LOCAL-ONLY, so these are filtered out of the picker and never run. Detected by
    the `:cloud`/`-cloud` tag in the name, or by the tell-tale tiny on-disk size of a cloud stub."""
    n = (name or "").lower()
    if ":cloud" in n or "-cloud" in n or n.endswith("cloud"):
        return True
    if size and 0 < size < _CLOUD_STUB_MAX_BYTES:   # a few-hundred-byte proxy stub, not weights
        return True
    return False


def set_model(name) -> None:
    """Pick the Ollama chat model used by every subsequent get_chat_model call, overriding
    OLLAMA_MODEL. Pass a falsy value to clear the override (fall back to OLLAMA_MODEL/.env).
    Any installed Ollama model is allowed — a LOCAL model (qwen3.5:9b, ornith:9b, …) OR an
    Ollama CLOUD model (glm-5.2:cloud, …) when the user picks one; cloud runs on Ollama's
    servers (account/`ollama signin` required) and is the stronger choice for hard designs
    (riscv, cgra). The default stays the local OLLAMA_MODEL unless the user picks cloud."""
    global _MODEL_OVERRIDE
    name = (name or "").strip() if isinstance(name, str) else ""
    _MODEL_OVERRIDE = name or None


def current_model() -> str:
    """The Ollama chat model in effect right now (the picker override if set, else .env). May be
    a local model OR an Ollama cloud model (`*:cloud`) when the user picked one."""
    return _MODEL_OVERRIDE or os.getenv("OLLAMA_MODEL", "qwen3.5:9b")


def list_ollama_models() -> "list[dict]":
    """Installed Ollama models (name + size + family) from the local Ollama daemon, so the UI
    can offer a picker. Best-effort: returns [] if Ollama isn't reachable. 100% local — these are
    whatever the user has pulled (`ollama pull …`), no cloud key required."""
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        import json as _json
        import urllib.request

        with urllib.request.urlopen(f"{base}/api/tags", timeout=4) as r:  # noqa: S310
            data = _json.loads(r.read().decode())
    except Exception:  # noqa: BLE001 — Ollama down / not installed → empty picker
        return []
    out = []
    for m in data.get("models", []):
        det = m.get("details") or {}
        name = m.get("name", "")
        size = int(m.get("size") or 0)
        param = det.get("parameter_size", "")
        if not name:
            continue
        # Include BOTH local and Ollama 'cloud' models, flagged so the UI can label which is which.
        # Cloud models (glm-5.2:cloud, …) run on Ollama's servers and are the stronger pick for hard
        # designs; local models run on this box. The user chooses per chat.
        out.append({
            "name": name,
            "size": size,
            "family": det.get("family", ""),
            "parameter_size": param,
            "cloud": is_cloud_model(name, size, param),
        })
    # local models first (they're the privacy-preserving default), then cloud, each alphabetical
    out.sort(key=lambda x: (x["cloud"], x["name"]))
    return out


def _ollama_has_vision(name: str) -> bool:
    """Does this Ollama model report a 'vision' capability in /api/show? Authoritative for LOCAL
    models. (Cloud stubs under-report — e.g. glm-5.2:cloud says no vision and indeed returns HTTP
    400 'this model does not support image input'.)"""
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        import json as _json
        import urllib.request

        req = urllib.request.Request(
            f"{base}/api/show", data=_json.dumps({"name": name}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=6) as r:  # noqa: S310
            info = _json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return False
    if "capabilities" in info:
        return any("vision" in str(c).lower() for c in (info.get("capabilities") or []))
    fam = " ".join(str(v) for v in (info.get("details") or {}).values()).lower()
    return any(k in (name + " " + fam).lower()
               for k in ("vl", "vision", "llava", "4v", "minicpm-v", "moondream"))


def vision_model() -> "str | None":
    """The model used to READ an image — DECOUPLED from the RTL chat model, so a user on a
    text-only model (e.g. glm-5.2:cloud, which Ollama rejects images for) still gets TRUE vision:
    a local VLM reads the diagram into text, then the strong model builds the RTL from that text.

    Resolution order: ANOA_VISION_MODEL env → the active chat model if IT reports vision → the
    first installed LOCAL model with a 'vision' capability (e.g. qwen3.5:9b, which works with
    think:false) → None. Google provider is handled separately in describe_image."""
    forced = os.getenv("ANOA_VISION_MODEL", "").strip()
    if forced:
        return forced
    if get_provider() != "ollama":
        return None
    cur = current_model()
    if not is_cloud_model(cur) and _ollama_has_vision(cur):
        return cur
    for m in list_ollama_models():            # any installed local VLM (image step ≠ RTL model)
        if not m["cloud"] and _ollama_has_vision(m["name"]):
            return m["name"]
    return None


def model_supports_vision(name: "str | None" = None) -> bool:
    """True when an uploaded image can be UNDERSTOOD by a model (vs. only OCR'd) — i.e. a vision
    model is available (the active one, or a local VLM for the image step). describe_image always
    falls back to OCR if the attempt yields nothing. ANOA_VISION forces on (1) / off (0)."""
    force = os.getenv("ANOA_VISION", "").strip().lower()
    if force in ("1", "true", "yes", "on"):
        return True
    if force in ("0", "false", "no", "off"):
        return False
    if get_provider() in ("google", "gemini"):
        return True
    return vision_model() is not None


def describe_image(image_path, prompt: str = "", temperature: float = 0.1) -> str:
    """Have a vision model DESCRIBE an image (a hardware block diagram / schematic / datasheet
    figure) as structured text an RTL agent can use — blocks, labels, bit-widths, connections.
    Routes to vision_model() (a local VLM when the chat model can't see). Returns '' on any failure
    (caller falls back to OCR)."""
    import base64
    from pathlib import Path as _Path

    p = _Path(image_path)
    try:
        data = p.read_bytes()
    except Exception:  # noqa: BLE001
        return ""
    fmt = (p.suffix.lstrip(".").lower() or "png")
    if fmt == "jpg":
        fmt = "jpeg"
    b64 = base64.b64encode(data).decode()
    instruction = prompt or (
        "You are reading a HARDWARE block diagram / schematic for an RTL engineer. Describe it "
        "PRECISELY and STRUCTURALLY: list every block/module with its exact label; for each, the "
        "bit-widths and signal names shown; and EVERY connection between blocks (source → "
        "destination, signal name, direction, width). Note any buses, clocks, resets, and "
        "interfaces (e.g. a CPU I/F to an accelerator). Output a tidy bulleted spec, not prose. "
        "If text is unreadable, say so rather than guessing.")
    provider = get_provider()
    if provider == "ollama":
        # Native /api/chat with `images` — more robust than langchain's image_url content blocks
        # (which 500'd on some models). `think:false` so a thinking model returns the answer in
        # `content` (not an empty content with a separate thinking channel — that's why qwen3.5:9b
        # looked broken). Routed to vision_model(), which is a working local VLM when the chat model
        # can't read images (e.g. glm-5.2:cloud).
        vm = vision_model()
        if not vm:
            return ""
        import json as _json
        import urllib.request

        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        # A MODEST context for the vision call: the image tokens + a short instruction + ~1k of
        # output fit easily in 8k, and a big window (the RTL slider's 32k+) makes the VLM's KV cache
        # blow past a tight GPU's VRAM → Ollama HTTP 500. Keep it small and bounded.
        vctx = min(int(os.getenv("OLLAMA_VISION_NUM_CTX", "8192")), _default_num_ctx() or 8192)
        body = {
            "model": vm,
            "messages": [{"role": "user", "content": instruction, "images": [b64]}],
            "stream": False, "think": False,
            "options": {"temperature": temperature, "num_ctx": vctx},
        }
        try:
            req = urllib.request.Request(
                f"{base}/api/chat", data=_json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            timeout = float(os.getenv("OLLAMA_VISION_TIMEOUT", "240"))  # cloud vision can be slow
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
                resp = _json.loads(r.read().decode())
            return ((resp.get("message") or {}).get("content") or "").strip()
        except Exception:  # noqa: BLE001 — backend can't read the image / call failed → OCR fallback
            return ""
    try:
        from langchain_core.messages import HumanMessage

        model = get_chat_model(temperature=temperature)
        msg = HumanMessage(content=[
            {"type": "text", "text": instruction},
            {"type": "image_url", "image_url": {"url": f"data:image/{fmt};base64,{b64}"}},
        ])
        resp = model.invoke([msg])
        return (getattr(resp, "content", "") or "").strip()
    except Exception:  # noqa: BLE001 — model can't take images / call failed → OCR fallback
        return ""


def get_provider() -> str:
    return os.getenv("LLM_PROVIDER", "ollama").strip().lower()


def provider_label() -> str:
    """Human-readable label for the active chat model (for the UI)."""
    provider = get_provider()
    if provider == "ollama":
        m = current_model()
        return f"Ollama · {m} ({'cloud' if is_cloud_model(m) else 'local'})"
    if provider in ("google", "gemini"):
        return f"Google · {os.getenv('GOOGLE_MODEL', 'gemini-2.5-pro')}"
    return provider


# --------------------------------------------------------------------------- #
# Token accounting — every LLM call through get_chat_model() is counted here
# (streaming, llm_query, deep-agent internals alike), so each pipeline step can
# report "🔢 N tokens" and the PDF report can state the total honestly.
# --------------------------------------------------------------------------- #
import threading as _threading

_TOKENS = {"in": 0, "out": 0, "calls": 0}
_TOK_LOCK = _threading.Lock()


def _count_usage(um) -> None:
    if not um:
        return
    with _TOK_LOCK:
        _TOKENS["in"] += int(um.get("input_tokens") or 0)
        _TOKENS["out"] += int(um.get("output_tokens") or 0)
        _TOKENS["calls"] += 1


from langchain_core.callbacks import BaseCallbackHandler as _BaseCB


class _TokenCounter(_BaseCB):
    """Minimal LangChain callback: harvests usage_metadata from every LLM result."""

    def on_llm_end(self, response, **kwargs):
        try:
            for gens in (getattr(response, "generations", None) or []):
                for g in gens:
                    msg = getattr(g, "message", None)
                    _count_usage(getattr(msg, "usage_metadata", None) or {})
        except Exception:  # noqa: BLE001
            pass


_TOKEN_CB = _TokenCounter()


def token_usage() -> dict:
    """Current process-wide token counters: {'in', 'out', 'calls'}."""
    with _TOK_LOCK:
        return dict(_TOKENS)


def count_subprocess_usage(input_tokens: int, output_tokens: int) -> None:
    """Fold in usage reported by out-of-process calls (run_python's llm() helper)."""
    _count_usage({"input_tokens": input_tokens, "output_tokens": output_tokens})


def fmt_tokens(n) -> str:
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    return f"{n / 1000:.1f}K" if n >= 1000 else str(n)


@functools.lru_cache(maxsize=1)
def _transient_exc_types() -> tuple:
    """The exception TYPES worth retrying — TRANSIENT network failures from Ollama's cloud
    proxy (`glm-5.2:cloud` runs on ollama.com; a blip surfaces as `dial tcp: lookup
    ollama.com … i/o timeout` / HTTP 502). Built from httpx + the ollama client so we retry
    connectivity ONLY — never a real error (bad prompt, auth, model-not-found). Falls back to
    OSError/TimeoutError if those libs aren't importable."""
    types: list = [ConnectionError, TimeoutError, OSError]
    try:
        import httpx
        types += [httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError,
                  httpx.RemoteProtocolError]
    except Exception:  # noqa: BLE001
        pass
    try:
        from ollama import ResponseError          # 502/503 from the cloud proxy
        types.append(ResponseError)
    except Exception:  # noqa: BLE001
        pass
    return tuple(dict.fromkeys(types))


def retrying(runnable):
    """Wrap a PLAIN runnable (e.g. `prompt | llm` used for planning/research/gists) so a
    TRANSIENT network error retries with backoff instead of aborting the step. A single
    ollama.com blip used to skip the whole web-research phase (`research skipped: … i/o
    timeout (502)`). NOTE: apply this to a piped runnable / at the CALL site — NEVER to the
    bare chat model returned by get_chat_model(), because the deep agent calls
    `.bind_tools()` on that model and a RunnableRetry has no bind_tools (it crashes the
    generate step)."""
    try:
        n = int(os.getenv("LLM_NET_RETRIES", "3"))
        if n <= 1 or not hasattr(runnable, "with_retry"):
            return runnable
        return runnable.with_retry(
            retry_if_exception_type=_transient_exc_types(),
            wait_exponential_jitter=True,
            stop_after_attempt=n,
        )
    except Exception:  # noqa: BLE001 — never let retry-wrapping break the call
        return runnable


def get_chat_model(temperature: float = 0.2, **kwargs):
    """
    Return a LangChain chat model for the configured provider.

    Args:
        temperature: sampling temperature.
        **kwargs: forwarded to the underlying ChatModel constructor.
    """
    provider = get_provider()

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        timeout = os.getenv("OLLAMA_TIMEOUT")
        extra = {}
        if timeout:
            # langchain-ollama forwards client kwargs; a generous timeout keeps
            # long RTL generations from being cut off.
            try:
                extra["client_kwargs"] = {"timeout": float(timeout)}
            except ValueError:
                pass
        # qwen3 is a "thinking" model: by default it streams a long internal
        # reasoning pass BEFORE any answer tokens, which on slow/offloaded hardware
        # looks like "no output" and wastes time. Default thinking OFF for speed;
        # set OLLAMA_THINK=1 to watch the model reason.
        think = os.getenv("OLLAMA_THINK", "0").strip().lower() in ("1", "true", "yes", "on")
        return ChatOllama(
            model=str(kwargs.pop("model", None) or current_model()),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=temperature,
            reasoning=think,
            callbacks=[_TOKEN_CB],        # token accounting (see token_usage())
            # --- Anti-repetition / runaway-generation guards ---
            # Small local models (esp. qwen) fall into degenerate loops where they
            # emit the SAME line(s) forever (e.g. "// We will assume … // But the
            # prompt says …"). A repeat penalty discourages the cycle, and a hard
            # num_predict cap guarantees generation STOPS even if a loop slips
            # through (otherwise it streams until OLLAMA_TIMEOUT). Tunable via .env.
            repeat_penalty=float(os.getenv("OLLAMA_REPEAT_PENALTY", "1.18")),
            repeat_last_n=int(os.getenv("OLLAMA_REPEAT_LAST_N", "256")),
            num_predict=int(os.getenv("OLLAMA_NUM_PREDICT", "8192")),
            # Ollama caps the context at 2048 tokens by DEFAULT regardless of the
            # model's real window (qwen3.5 supports up to ~1M). That truncates the
            # RAG prompt and makes the model return NOTHING — the empty-output bug.
            # Raise it via OLLAMA_NUM_CTX. The KV cache costs ~56 KB/token for this
            # 9B model, so num_ctx is bounded by RAM/VRAM, not the model: 128k≈7 GB
            # and 256k≈15 GB of KV cache. On a 14 GB-RAM / 8 GB-VRAM box, 16k is the
            # sweet spot (holds the references with room to spare). A bigger window
            # does NOT improve output — it only needs to fit the prompt (~5-8k here).
            num_ctx=int(kwargs.pop("num_ctx", None) or _default_num_ctx()),
            **extra,
            **kwargs,
        )

    if provider in ("google", "gemini"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "LLM_PROVIDER=google but GOOGLE_API_KEY is not set. "
                "Add it to your .env file or switch LLM_PROVIDER=ollama."
            )
        return ChatGoogleGenerativeAI(
            model=os.getenv("GOOGLE_MODEL", "gemini-2.5-pro"),
            google_api_key=api_key,
            temperature=temperature,
            **kwargs,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER={provider!r}. Use 'ollama' or 'google'."
    )


@functools.lru_cache(maxsize=1)
def get_embeddings():
    """
    Return a LangChain embeddings object for the configured provider.

    Cached because loading a sentence-transformers model is expensive.

    NOTE: the prebuilt FAISS indexes in data/verilog_datasets were created with
    all-MiniLM-L6-v2 (384-dim). Keep EMBEDDINGS_PROVIDER=huggingface unless you
    rebuild those indexes, otherwise dimensions will not match.
    """
    provider = os.getenv("EMBEDDINGS_PROVIDER", "huggingface").strip().lower()

    if provider == "huggingface":
        from langchain_huggingface import HuggingFaceEmbeddings

        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
        return HuggingFaceEmbeddings(
            model_name=os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
            model_kwargs={"device": device},
        )

    if provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )

    if provider in ("google", "gemini"):
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(
            model="models/embedding-001",
            google_api_key=os.getenv("GOOGLE_API_KEY"),
        )

    raise ValueError(
        f"Unknown EMBEDDINGS_PROVIDER={provider!r}. "
        "Use 'huggingface', 'ollama', or 'google'."
    )


@functools.lru_cache(maxsize=1)
def get_reranker():
    """Local cross-encoder reranker (sentence-transformers ``CrossEncoder``) — the precision
    stage of the RAG pipeline. The bi-encoder/BM25 retrieval is recall-oriented (cheap, broad);
    the cross-encoder reads each (query, passage) pair JOINTLY and scores true relevance, so the
    few chunks we feed the small-context model are the BEST ones — maximal signal per token.

    Default ``cross-encoder/ms-marco-MiniLM-L-6-v2`` (~80 MB, fast on CPU). Set
    ANOA_RERANKER_MODEL=BAAI/bge-reranker-base for a stronger/larger model. Returns None when
    disabled (ANOA_RAG_RERANK=0) or unavailable (offline first run, missing lib) so callers
    gracefully fall back to fusion order. 100% local + free."""
    if os.getenv("ANOA_RAG_RERANK", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    try:
        from sentence_transformers import CrossEncoder
        # Default the reranker to CPU: it's tiny and fast there, and on a VRAM-tight box the GPU
        # is better left to Ollama's weights + KV cache. Override with ANOA_RERANKER_DEVICE=cuda.
        device = os.getenv("ANOA_RERANKER_DEVICE", "cpu").strip().lower()
        model = os.getenv("ANOA_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        return CrossEncoder(model, max_length=512, device=device)
    except Exception:  # noqa: BLE001 - any failure → no reranker, fall back to fusion order
        return None


def _detect_memory_bytes() -> "tuple[int, str]":
    """(usable_bytes, device) for sizing the KV cache: GPU VRAM when CUDA is present, else
    system RAM (Ollama can run the model on CPU). Best-effort; 0 if nothing detectable."""
    # 1) GPU VRAM via torch
    try:
        import torch
        if torch.cuda.is_available():
            return int(torch.cuda.get_device_properties(0).total_memory), "cuda"
    except Exception:  # noqa: BLE001
        pass
    # 2) GPU VRAM via nvidia-smi (no torch / torch without CUDA build)
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4)
        mb = max(int(x) for x in out.stdout.split() if x.strip().isdigit())
        if mb > 0:
            return mb * 1024 * 1024, "cuda"
    except Exception:  # noqa: BLE001
        pass
    # 3) system RAM (CPU inference)
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages) * int(page_size), "cpu"
    except Exception:  # noqa: BLE001
        return 0, "cpu"


def recommended_ctx_limits() -> dict:
    """Size the context-window (num_ctx) slider to the user's HARDWARE so they can't pick a
    window whose KV cache won't fit. For this 9B model the KV cache costs ~56 KB/token, and the
    model weights (~6 GB at q4) must be resident first; the rest of VRAM (or RAM, on CPU) is the
    KV-cache budget. Returns {device, total_gb, num_ctx_min, num_ctx_max, num_ctx_default}.

    Tunables: OLLAMA_KV_BYTES_PER_TOKEN, OLLAMA_RESERVE_GB (weights+overhead), OLLAMA_CTX_HARD_MAX."""
    total, device = _detect_memory_bytes()
    kv_per_tok = int(os.getenv("OLLAMA_KV_BYTES_PER_TOKEN", str(56 * 1024)))
    reserve_gb = float(os.getenv("OLLAMA_RESERVE_GB", "6.0" if device == "cuda" else "8.0"))
    hard_max = int(os.getenv("OLLAMA_CTX_HARD_MAX", "262144"))  # qwen3.5 supports a huge window
    step = 2048
    if total > 0:
        budget = max(0.0, total * 0.90 - reserve_gb * 1e9)      # 10% headroom + weights
        raw = int(budget / kv_per_tok)
        num_ctx_max = max(4096, min(hard_max, (raw // step) * step))
    else:
        num_ctx_max = int(os.getenv("OLLAMA_NUM_CTX", "32768"))  # detection failed → safe default
    num_ctx_default = min(num_ctx_max, _default_num_ctx())
    return {
        "device": device,
        "total_gb": round(total / 1e9, 1) if total else 0.0,
        "num_ctx_min": 2048,
        "num_ctx_max": int(num_ctx_max),
        "num_ctx_step": step,
        "num_ctx_default": int(num_ctx_default),
    }
