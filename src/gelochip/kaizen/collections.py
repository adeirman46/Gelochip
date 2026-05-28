"""
gelochip.kaizen.collections  —  the three local ChromaDB knowledge collections.

    1. glayout_knowledge        DRC-clean glayout code/layout knowledge   
                                (ingested from data/glayout_code/*.jsonl)
    2. rf_theory                RF/mmWave books, papers, EE QA, PySpice corpus
                                (ingested from data/rf_theory/**)
    3. error_feedback           error → root cause → fix memory (starts EMPTY,
                                grown by the Kaizen loop at runtime).

All three live in a single persistent ChromaDB instance (``config.CHROMA_DIR``)
as distinct *collections* — one database server, three tables. Both query and
write paths go through LangChain ``Chroma`` vector stores sharing one embedder.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Iterable

from gelochip.kaizen import config
from gelochip.kaizen.embeddings import get_embeddings


# ── Vector-store handles ──────────────────────────────────────────────────────
def get_vectorstore(collection: str, persist_dir=None):
    """Open (or create) one LangChain Chroma collection on disk.

    Defaults to the permanent store (``config.CHROMA_DIR`` under data/). Pass
    ``persist_dir`` (e.g. the per-job research DB under outputs/) for temp stores.
    """
    from langchain_chroma import Chroma

    config.ensure_dirs()
    return Chroma(
        collection_name=collection,
        embedding_function=get_embeddings(),
        persist_directory=str(persist_dir or config.CHROMA_DIR),
    )


def collection_counts() -> dict[str, int]:
    """Return the number of stored chunks per collection."""
    counts: dict[str, int] = {}
    for name in config.ALL_COLLECTIONS:
        try:
            counts[name] = get_vectorstore(name)._collection.count()
        except Exception:
            counts[name] = 0
    return counts


# ── helpers ───────────────────────────────────────────────────────────────────
def _splitter(chunk_size: int = 1200, overlap: int = 150):
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)


_CIRCUIT_HINTS = (
    "current mirror", "diff pair", "differential pair", "ota", "amplifier",
    "inverter", "fvf", "cascode", "lna", "mixer", "vco", "oscillator",
    "common source", "common gate", "level shifter", "bandgap", "transmission gate",
)


def _guess_circuit(text: str) -> str:
    low = text.lower()
    for hint in _CIRCUIT_HINTS:
        if hint in low:
            return hint.replace(" ", "_")
    return "generic"


def _slug(text: str, maxlen: int = 24) -> str:
    """Make a short, filesystem/ID-safe slug from text."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:maxlen] or "doc").strip("-")


def _add_documents(store, docs: list, prefix: str, batch: int = 256) -> int:
    """Add LangChain Documents with meaningful, readable IDs (not random UUIDs).

    IDs look like ``tmpl-current_mirror-00007`` or ``theory-bowick-00042`` so the
    on-disk collection is self-describing instead of ``446df...``.
    """
    n = 0
    for i in range(0, len(docs), batch):
        chunk = docs[i : i + batch]
        ids = []
        for j, d in enumerate(chunk):
            tag = d.metadata.get("circuit") or d.metadata.get("source") or "doc"
            ids.append(f"{prefix}-{_slug(str(tag))}-{i + j:05d}")
        store.add_documents(chunk, ids=ids)
        n += len(chunk)
    return n


# ── Collection 1: glayout code templates ──────────────────────────────────────
def ingest_templates(reset: bool = True) -> int:
    """Ingest human→glayout-code pairs from the SFT JSONL datasets."""
    from langchain_core.documents import Document

    store = get_vectorstore(config.COLL_TEMPLATES)
    if reset:
        _reset(store)

    jsonl_files = sorted(config.SFT_DATASET_DIR.glob("dataset_*.jsonl"))
    docs: list[Document] = []
    seen: set[str] = set()

    for jf in jsonl_files:
        for line in jf.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            convo = rec.get("conversations", [])
            human = next((m["value"] for m in convo if m["from"] == "human"), "")
            gpt = next((m["value"] for m in convo if m["from"] == "gpt"), "")
            if not human or not gpt:
                continue
            key = human[:120]
            if key in seen:
                continue
            seen.add(key)
            # page_content holds instruction + code so retrieval returns runnable code.
            content = f"# Task\n{human}\n\n# glayout solution\n{gpt}"
            docs.append(
                Document(
                    page_content=content,
                    metadata={
                        "source": jf.name,
                        "circuit": _guess_circuit(human),
                        "pdk": config.PDK,
                        "doc_type": "code_template",
                    },
                )
            )
    n = _add_documents(store, docs, prefix="tmpl")

    # Also ingest the verified DRC-clean circuit reimplementations (data/circuits/*).
    clean_docs: list[Document] = []
    for clean_py in sorted(config.CIRCUITS_DIR.glob("*/*_clean.py")):
        circuit = clean_py.parent.name
        code = clean_py.read_text()
        clean_docs.append(Document(
            page_content=f"# Task\nGenerate DRC-clean glayout code for a "
                         f"{circuit.replace('_', ' ')} on gf180 PDK.\n\n"
                         f"# glayout solution (DRC-verified)\n{code}",
            metadata={"source": clean_py.name, "circuit": circuit, "pdk": config.PDK,
                      "doc_type": "clean_circuit", "status": "verified_correct"},
        ))
    n += _add_documents(store, clean_docs, prefix="clean")
    return n


def add_template(instruction: str, code: str, circuit: str = "generic",
                 source: str = "corrected", also_jsonl: bool = True) -> str:
    """Promote a verified (DRC-clean) instruction→glayout-code pair into RAG.

    Closes the Kaizen loop: a corrected block is (1) ingested into the
    ``glayout_knowledge`` ChromaDB collection so future generations
    retrieve it, and (2) appended to the clean JSONL dataset so the dataset
    of record grows too.
    """
    from langchain_core.documents import Document

    store = get_vectorstore(config.COLL_TEMPLATES)
    content = f"# Task\n{instruction}\n\n# glayout solution\n{code}"
    _id = f"tmpl-{_slug(circuit)}-{source}-{uuid.uuid4().hex[:6]}"
    store.add_documents([Document(
        page_content=content,
        metadata={"source": source, "circuit": circuit, "pdk": config.PDK,
                  "doc_type": "code_template", "status": "verified_correct"},
    )], ids=[_id])

    if also_jsonl:
        append_to_jsonl_dataset(instruction, code)
    return _id


def append_to_jsonl_dataset(instruction: str, code: str,
                            path: Path | None = None) -> Path:
    """Append a conversation record to the corrected SFT/RAG JSONL dataset."""
    path = path or (config.SFT_DATASET_DIR / "dataset_corrected.jsonl")
    rec = {"conversations": [
        {"from": "human", "value": instruction},
        {"from": "gpt", "value": code},
    ]}
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return path


# ── Collection 2: RF / mmWave theory ──────────────────────────────────────────
def ingest_theory(reset: bool = True, parse_pdfs: bool = False) -> int:
    """Ingest RF/mmWave theory from extracted texts, abstracts, EE QA, PySpice."""
    from langchain_core.documents import Document

    store = get_vectorstore(config.COLL_THEORY)
    if reset:
        _reset(store)

    splitter = _splitter()
    docs: list[Document] = []

    # (a) Extracted book / standards texts (steer, bowick, mit, nist …).
    for txt in sorted((config.RAW_DATA_DIR / "texts").glob("*.txt")):
        text = txt.read_text(errors="ignore")
        for chunk in splitter.split_text(text):
            docs.append(Document(page_content=chunk,
                                 metadata={"source": txt.stem, "doc_type": "book"}))

    # (b) ArXiv abstracts (one big file of RF/EM/IC abstracts).
    abstracts = config.RAW_DATA_DIR / "arxiv" / "all_abstracts.txt"
    if abstracts.exists():
        for chunk in splitter.split_text(abstracts.read_text(errors="ignore")):
            docs.append(Document(page_content=chunk,
                                 metadata={"source": "arxiv_abstracts", "doc_type": "paper"}))

    # (c) HuggingFace electrical-engineering QA datasets.
    for jf in sorted((config.RAW_DATA_DIR / "huggingface").glob("*.jsonl")):
        for line in jf.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = _flatten_record(rec)
            if text:
                docs.append(Document(page_content=text,
                                     metadata={"source": jf.stem, "doc_type": "ee_qa"}))

    # (d) AnalogCoder / PySpice instruction→code pairs.
    pyspice = config.RAW_DATA_DIR / "analog_pyspice" / "sft_pairs.jsonl"
    if pyspice.exists():
        for line in pyspice.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            instr, out = rec.get("instruction", ""), rec.get("output", "")
            if instr and out:
                docs.append(Document(
                    page_content=f"# {instr}\n\n{out}",
                    metadata={"source": "analog_pyspice", "doc_type": "pyspice_example",
                              "circuit": rec.get("circuit", "")}))

    # (e) Optional: parse raw PDFs not yet extracted to text.
    if parse_pdfs:
        docs += _ingest_pdfs(config.RAW_DATA_DIR / "books", splitter)
        docs += _ingest_pdfs(config.RAW_DATA_DIR / "arxiv" / "pdfs", splitter)

    return _add_documents(store, docs, prefix="theory")


def _flatten_record(rec: dict) -> str:
    """Turn a QA-style JSON record into a single text blob."""
    for q, a in (("question", "answer"), ("instruction", "output"), ("prompt", "response")):
        if rec.get(q):
            return f"Q: {rec[q]}\nA: {rec.get(a, '')}".strip()
    if rec.get("text"):
        return str(rec["text"])
    return " ".join(str(v) for v in rec.values() if isinstance(v, str))[:2000]


def _ingest_pdfs(folder: Path, splitter) -> list:
    from langchain_core.documents import Document
    from pypdf import PdfReader

    out: list[Document] = []
    if not folder.exists():
        return out
    for pdf in sorted(folder.glob("*.pdf")):
        try:
            reader = PdfReader(str(pdf))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            continue
        for chunk in splitter.split_text(text):
            out.append(Document(page_content=chunk,
                                metadata={"source": pdf.stem, "doc_type": "pdf"}))
    return out


# ── Collection 3: Kaizen lessons learned ──────────────────────────────────────
def ingest_lessons(reset: bool = True) -> int:
    """Seed the Kaizen memory from a JSON seed file of known error→fix lessons."""
    from langchain_core.documents import Document

    store = get_vectorstore(config.COLL_LESSONS)
    if reset:
        _reset(store)

    seed = config.KAIZEN_DIR / "lessons_seed.json"
    if not seed.exists():
        return 0
    lessons = json.loads(seed.read_text())
    docs = [
        Document(page_content=_lesson_text(l),
                 metadata={"circuit": l.get("circuit", "generic"),
                           "status": l.get("status", "verified_correct"),
                           "doc_type": "lesson", "source": "seed"})
        for l in lessons
    ]
    return _add_documents(store, docs, prefix="lesson")


def _lesson_text(l: dict) -> str:
    return (
        f"Scenario: {l.get('scenario', '')}\n"
        f"Symptom / error: {l.get('error', '')}\n"
        f"Root cause: {l.get('root_cause', '')}\n"
        f"Fix: {l.get('fix', '')}"
    )


def add_lesson(scenario: str, error: str, root_cause: str, fix: str,
               circuit: str = "generic", status: str = "verified_correct") -> str:
    """Append a single problem→fix lesson to the Kaizen memory at runtime."""
    from langchain_core.documents import Document

    store = get_vectorstore(config.COLL_LESSONS)
    doc = Document(
        page_content=_lesson_text(
            {"scenario": scenario, "error": error, "root_cause": root_cause, "fix": fix}),
        metadata={"circuit": circuit, "status": status, "doc_type": "lesson",
                  "source": "kaizen_runtime"},
    )
    _id = f"lesson-{_slug(circuit)}-rt-{uuid.uuid4().hex[:6]}"
    store.add_documents([doc], ids=[_id])
    return _id


# ── build everything ──────────────────────────────────────────────────────────
def build_all(parse_pdfs: bool = False, seed_feedback: bool = False) -> dict[str, int]:
    """(Re)build the collections from source datasets. Run once.

    Collection 3 (``error_feedback``) starts EMPTY by design — it is the runtime
    error→fix memory the Kaizen loop writes to via :func:`add_lesson`. Pass
    ``seed_feedback=True`` to also load ``lessons_seed.json``.
    """
    # Always reset collection 3 so it begins empty.
    _reset(get_vectorstore(config.COLL_LESSONS))
    return {
        config.COLL_TEMPLATES: ingest_templates(reset=True),
        config.COLL_THEORY: ingest_theory(reset=True, parse_pdfs=parse_pdfs),
        config.COLL_LESSONS: ingest_lessons(reset=True) if seed_feedback else 0,
    }


def _reset(store) -> None:
    """Drop all vectors in a collection so it can be re-ingested cleanly."""
    try:
        ids = store._collection.get()["ids"]
        if ids:
            store._collection.delete(ids=ids)
    except Exception:
        pass
