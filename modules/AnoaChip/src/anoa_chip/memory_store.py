"""
AnoaChip durable knowledge store — the RLM's long-term memory.

A SEPARATE Postgres database (``anoachip``) + MinIO bucket (``anoachip``) on the
local docker stack (docker-compose.yml: postgres[pgvector] + minio). Everything
AnoaChip sees or makes — generated config/netlist/testbench, glayout scripts, sim
logs, GDS, design notes, crawled GitHub/paper references, uploaded PDFs/images, and
the gLayout cell/tutorial corpus — is stored two ways:

  • a BLOB in MinIO object storage (the raw file),
  • a ROW in Postgres ``knowledge`` (durable, queryable record of truth) that ALSO
    carries the embedding ``vector`` for semantic recall (pgvector).

so each new design can RECALL relevant prior knowledge (a past design, a fix, a
reference, a datasheet) and the RLM gets better the more it is used.

Semantic recall lives entirely IN Postgres via the ``pgvector`` extension — the
embedding is a ``vector`` column, recall is ``ORDER BY embedding <=> :query``. No
FAISS file: catalog AND vectors share one row, so similarity can be combined with
SQL metadata filters (kind / design) in a single query. The embedding model is the
same sentence-transformers model the rest of the app uses.

100% local + free, config-driven, DEFENSIVE: if the DB / bucket / libraries are
unavailable, every call no-ops and the agent keeps running on the local file flow.
Connection is via env (defaults point at AnoaChip's own docker stack):

  ANOA_DATABASE_URL   postgresql+psycopg://anoa:anoa@localhost:5434/anoachip
  ANOA_S3_ENDPOINT_URL  http://localhost:9102
  ANOA_S3_ACCESS_KEY / ANOA_S3_SECRET_KEY   anoa / anoasecret
  ANOA_S3_BUCKET      anoachip
  ANOA_MEMORY=0       to disable entirely

Bring the stack up with: ``docker compose up -d``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("anoa.memory")

REPO_ROOT = Path(__file__).resolve().parents[2]
# Committed seed so a fresh clone is NOT empty (an empty store hurts the agent).
# rows.jsonl.gz = every knowledge row incl. its embedding; blobs/ = the raw files.
SEED_DIR = REPO_ROOT / "data" / "knowledge_seed"
SEED_ROWS = SEED_DIR / "rows.jsonl.gz"
SEED_BLOBS = SEED_DIR / "blobs"


def _blob_filename(object_key: str) -> str:
    """A filesystem-safe, reversible-enough name for a blob in the committed seed."""
    return re.sub(r"[^\w.\-]", "__", object_key)

# Extensions we embed inline (their text goes into the recall vector); everything
# else is stored as a blob with a short descriptive note as its searchable text.
# Analog: SPICE netlists (.sp/.spice/.cir/.cdl), glayout generators (.py) and config
# (.json) are the code deliverables; .lib/.spice testbenches + sim logs are context.
_TEXT_EXT = {".sp", ".spice", ".cir", ".cdl", ".spc", ".py", ".md", ".txt",
             ".log", ".json", ".tcl", ".sdc", ".csv", ".rst", ".lib", ".rpt"}
_BIN_NOTE = {".gds": "GDSII layout", ".png": "image", ".jpg": "image",
             ".jpeg": "image", ".webp": "image", ".svg": "vector image",
             ".pdf": "PDF document"}
# Raster images we OCR on ingest (svg/gds are NOT raster → no OCR, just a note).
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def _hash_id(*parts) -> str:
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]
    return "k_" + h


def _kind_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".sp", ".spice", ".cir", ".cdl", ".spc"):
        return "code"          # SPICE netlist
    if ext == ".py":
        return "code"          # glayout generator
    if ext == ".json":
        return "design"        # a config file
    if ext == ".gds":
        return "gds"
    if ext == ".pdf":
        return "pdf"
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
        return "image"
    if ext == ".md":
        return "md"
    if ext in (".log", ".rpt"):
        return "sim"
    return "note"


def _vec_literal(vec) -> str:
    """pgvector accepts a '[f1,f2,...]' string literal cast to ::vector — no extra lib."""
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def _env_on(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# Reciprocal Rank Fusion constant (Cormack et al. 2009; the standard hybrid-search merge used by
# Elasticsearch/Weaviate/RAG-Fusion). Larger k flattens the weight of top ranks.
_RRF_K = 60


def _rrf_fuse(ranked_lists: "list[list[dict]]", k: int = _RRF_K) -> "list[dict]":
    """Merge several ranked candidate lists by Reciprocal Rank Fusion: an item's fused score is
    sum(1 / (k + rank)) across the lists it appears in. Rank-based, so it combines incomparable
    scales (cosine similarity vs. BM25/ts_rank) without tuning weights. Returns one de-duplicated
    list ordered best-first, each item carrying its 'score' (the RRF score)."""
    scores: dict = {}
    items: dict = {}
    for lst in ranked_lists:
        for rank, it in enumerate(lst):
            rid = it.get("id")
            if rid is None:
                continue
            items.setdefault(rid, it)
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)
    fused = sorted(items.values(), key=lambda it: scores[it["id"]], reverse=True)
    for it in fused:
        it["score"] = scores[it["id"]]
    return fused


class MemoryStore:
    def __init__(self) -> None:
        self.db_url = os.getenv(
            "ANOA_DATABASE_URL",
            "postgresql+psycopg://anoa:anoa@localhost:5434/anoachip")
        self.s3_endpoint = os.getenv("ANOA_S3_ENDPOINT_URL", "http://localhost:9102")
        self.s3_key = os.getenv("ANOA_S3_ACCESS_KEY", "anoa")
        self.s3_secret = os.getenv("ANOA_S3_SECRET_KEY", "anoasecret")
        self.s3_bucket = os.getenv("ANOA_S3_BUCKET", "anoachip")
        self.s3_region = os.getenv("ANOA_S3_REGION", "us-east-1")

        self._engine = None
        self._s3 = None
        self._emb = None             # embeddings model (lazy)
        self._embed_dim = None
        self._db_ready = False
        self._s3_ready = False
        self._vec_ready = False      # pgvector column + index created
        self._fts_ready = False      # full-text (GIN) index created — the lexical half of hybrid

        if os.getenv("ANOA_MEMORY", "1").lower() in ("0", "false", "no", "off"):
            logger.info("AnoaChip memory store disabled by ANOA_MEMORY.")
            return
        self._init_db()
        self._init_s3()

    @property
    def enabled(self) -> bool:
        return self._db_ready or self._s3_ready

    # --- clients / schema --------------------------------------------------
    def _ensure_database(self) -> None:
        """CREATE DATABASE anoachip if missing (connect to the admin 'postgres' db)."""
        from sqlalchemy import create_engine, text as sqltext
        from sqlalchemy.engine import make_url
        url = make_url(self.db_url)
        admin = create_engine(url.set(database="postgres"),
                              isolation_level="AUTOCOMMIT", future=True)
        try:
            with admin.connect() as conn:
                exists = conn.execute(
                    sqltext("SELECT 1 FROM pg_database WHERE datname=:n"),
                    {"n": url.database}).scalar()
                if not exists:
                    conn.execute(sqltext(f'CREATE DATABASE "{url.database}"'))
                    logger.info("Created database %s", url.database)
        finally:
            admin.dispose()

    def _init_db(self) -> None:
        try:
            from sqlalchemy import (Column, DateTime, MetaData, String, Table, Text,
                                    create_engine, text as sqltext)
            from sqlalchemy.dialects.postgresql import JSONB
            self._ensure_database()
            self._engine = create_engine(self.db_url, pool_pre_ping=True, future=True)
            with self._engine.begin() as conn:
                conn.execute(sqltext("CREATE EXTENSION IF NOT EXISTS vector"))
            md = MetaData()
            Table(
                "knowledge", md,
                Column("id", String, primary_key=True),
                Column("kind", String, index=True),       # design|code|fix|reference|paper|md|gds|image|pdf|sim|note
                Column("design", String, index=True),
                Column("source", String),                 # github url / file path / run id
                Column("title", String),
                Column("text", Text),                      # the searchable snippet/summary
                Column("object_key", String),             # MinIO blob key (or null)
                Column("tags", String),
                Column("meta", JSONB),
                Column("created_at", DateTime(timezone=True)),
                # `embedding vector(N)` is added lazily once we know the model's dim.
            )
            md.create_all(self._engine)
            self._db_ready = True
            logger.info("AnoaChip knowledge DB ready (%s).", self.db_url.split("@")[-1])
        except Exception as exc:  # noqa: BLE001
            logger.warning("knowledge DB disabled (%s): %s", type(exc).__name__, exc)
            self._engine = None
            self._db_ready = False

    def _embeddings(self):
        if self._emb is None:
            from llm import get_embeddings
            self._emb = get_embeddings()
        return self._emb

    def _ensure_vector(self, dim: int | None = None) -> bool:
        """Lazily add the pgvector column + HNSW index once we know the embedding dim.
        Pass `dim` (e.g. from a seed row) to avoid loading the embeddings model — used
        by the seed import so a fresh clone fills the DB without recomputing vectors."""
        if self._vec_ready:
            return True
        if not self._db_ready:
            return False
        try:
            from sqlalchemy import text as sqltext
            dim = dim or len(self._embeddings().embed_query("probe"))
            self._embed_dim = dim
            with self._engine.begin() as conn:
                conn.execute(sqltext(
                    f"ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS embedding vector({dim})"))
                conn.execute(sqltext(
                    "CREATE INDEX IF NOT EXISTS knowledge_embedding_idx ON knowledge "
                    "USING hnsw (embedding vector_cosine_ops)"))
            self._vec_ready = True
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("pgvector setup failed: %s", exc)
            return False

    _FTS_EXPR = "to_tsvector('english', coalesce(title,'') || ' ' || coalesce(text,''))"

    def _ensure_fts(self) -> bool:
        """Lazily build the GIN full-text index over title+text — the lexical (BM25-like) half of
        hybrid retrieval. The index expression MUST match the query expression exactly for Postgres
        to use it. No-op + returns False if the DB is down (recall then runs dense-only)."""
        if self._fts_ready:
            return True
        if not self._db_ready:
            return False
        try:
            from sqlalchemy import text as sqltext
            with self._engine.begin() as conn:
                conn.execute(sqltext(
                    "CREATE INDEX IF NOT EXISTS knowledge_fts_idx ON knowledge "
                    f"USING gin ({self._FTS_EXPR})"))
            self._fts_ready = True
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("full-text index setup failed: %s", exc)
            return False

    def _init_s3(self) -> None:
        try:
            import boto3
            from botocore.config import Config as BotoConfig
            self._s3 = boto3.client(
                "s3", endpoint_url=self.s3_endpoint,
                aws_access_key_id=self.s3_key, aws_secret_access_key=self.s3_secret,
                region_name=self.s3_region,
                config=BotoConfig(signature_version="s3v4", retries={"max_attempts": 2}))
            try:
                self._s3.head_bucket(Bucket=self.s3_bucket)
            except Exception:  # noqa: BLE001 - create if missing
                self._s3.create_bucket(Bucket=self.s3_bucket)
            self._s3_ready = True
            logger.info("AnoaChip object storage ready (bucket=%s).", self.s3_bucket)
        except Exception as exc:  # noqa: BLE001
            logger.warning("object storage disabled (%s): %s", type(exc).__name__, exc)
            self._s3 = None
            self._s3_ready = False

    # --- object storage ----------------------------------------------------
    def put_object(self, key: str, local_path) -> str | None:
        if not self._s3_ready:
            return None
        p = Path(local_path)
        if not p.exists():
            return None
        try:
            self._s3.upload_file(str(p), self.s3_bucket, key)
            return key
        except Exception as exc:  # noqa: BLE001
            logger.warning("put_object %s failed: %s", key, exc)
            return None

    def get_object(self, key: str) -> bytes | None:
        if not self._s3_ready or not key:
            return None
        try:
            return self._s3.get_object(Bucket=self.s3_bucket, Key=key)["Body"].read()
        except Exception:  # noqa: BLE001
            return None

    # --- the two primitives: remember + recall -----------------------------
    def remember(self, kind: str, text: str = "", *, design: str = "", source: str = "",
                 title: str = "", tags: str = "", object_local_path=None,
                 object_key: str | None = None, meta: dict | None = None,
                 embedding=None) -> str | None:
        """Store one knowledge item: optional blob → MinIO, row (+embedding) → Postgres.
        Pass `embedding` (a precomputed vector) to skip re-embedding — used by the
        FAISS→pgvector migration to reuse existing vectors. Returns the item id."""
        if not self.enabled:
            return None
        rid = _hash_id(kind, design, source, title, (text or "")[:200], object_key or "")
        okey = object_key
        if object_local_path:
            p = Path(object_local_path)
            if p.exists():
                okey = okey or f"anoa/{design or 'misc'}/{p.name}"
                self.put_object(okey, p)
        dim = len(embedding) if embedding is not None else None
        if self._db_ready and self._ensure_vector(dim=dim):
            try:
                from sqlalchemy import text as sqltext
                body = (text or title).strip()[:4000]
                emb = (_vec_literal(embedding) if embedding is not None
                       else _vec_literal(self._embeddings().embed_query(body or title or kind)))
                with self._engine.begin() as conn:
                    conn.execute(sqltext("""
                        INSERT INTO knowledge
                          (id, kind, design, source, title, text, object_key, tags, meta,
                           embedding, created_at)
                        VALUES
                          (:id, :kind, :design, :source, :title, :text, :object_key, :tags,
                           CAST(:meta AS JSONB), CAST(:emb AS vector), :created_at)
                        ON CONFLICT (id) DO UPDATE SET
                          text=EXCLUDED.text, title=EXCLUDED.title,
                          object_key=EXCLUDED.object_key, tags=EXCLUDED.tags,
                          meta=EXCLUDED.meta, embedding=EXCLUDED.embedding
                    """), {
                        "id": rid, "kind": kind, "design": design, "source": source,
                        "title": title[:500], "text": text, "object_key": okey, "tags": tags,
                        "meta": json.dumps(meta or {}), "emb": emb,
                        "created_at": datetime.now(timezone.utc),
                    })
            except Exception as exc:  # noqa: BLE001
                logger.warning("remember row failed: %s", exc)
        return rid

    # --- retrieval stages (hybrid: dense + lexical → RRF → cross-encoder rerank) ----
    def _dense_candidates(self, query: str, kind, design, n: int) -> list[dict]:
        """Bi-encoder (pgvector cosine) recall — semantic, recall-oriented."""
        if not (self._db_ready and self._ensure_vector()):
            return []
        try:
            from sqlalchemy import text as sqltext
            emb = _vec_literal(self._embeddings().embed_query(query))
            conds, params = ["embedding IS NOT NULL"], {"emb": emb, "k": int(n)}
            if kind:
                conds.append("kind = :kind")
                params["kind"] = kind
            if design:
                conds.append("design = :design")
                params["design"] = design
            sql = (
                "SELECT id, kind, design, source, title, text, object_key, "
                "       1 - (embedding <=> CAST(:emb AS vector)) AS score "
                "FROM knowledge WHERE " + " AND ".join(conds) +
                " ORDER BY embedding <=> CAST(:emb AS vector) LIMIT :k")
            with self._engine.begin() as conn:
                return [dict(r) for r in conn.execute(sqltext(sql), params).mappings().all()]
        except Exception as exc:  # noqa: BLE001
            logger.warning("dense recall failed: %s", exc)
            return []

    def _lexical_candidates(self, query: str, kind, design, n: int) -> list[dict]:
        """Postgres full-text (BM25-like ts_rank_cd) recall — catches exact tokens the embedding
        blurs: module/signal names, opcodes, error strings, part numbers. The other half of hybrid."""
        if not (self._db_ready and self._ensure_fts()):
            return []
        try:
            from sqlalchemy import text as sqltext
            conds = [f"{self._FTS_EXPR} @@ plainto_tsquery('english', :q)"]
            params = {"q": query, "k": int(n)}
            if kind:
                conds.append("kind = :kind")
                params["kind"] = kind
            if design:
                conds.append("design = :design")
                params["design"] = design
            sql = (
                "SELECT id, kind, design, source, title, text, object_key, "
                f"       ts_rank_cd({self._FTS_EXPR}, plainto_tsquery('english', :q)) AS score "
                "FROM knowledge WHERE " + " AND ".join(conds) +
                " ORDER BY score DESC LIMIT :k")
            with self._engine.begin() as conn:
                return [dict(r) for r in conn.execute(sqltext(sql), params).mappings().all()]
        except Exception as exc:  # noqa: BLE001
            logger.warning("lexical recall failed: %s", exc)
            return []

    def _rerank(self, query: str, items: list[dict], k: int) -> list[dict]:
        """Cross-encoder reranking — read each (query, passage) pair JOINTLY and re-score, then keep
        the top-k. This is the precision stage that lets a small-context model thrive: we retrieve
        broadly, then feed only the few genuinely-relevant chunks. Falls back to input order if the
        reranker is unavailable."""
        if not items:
            return items
        try:
            from llm import get_reranker
            ce = get_reranker()
            if ce is None:
                return items[:k]
            pairs = [(query, ((it.get("title") or "") + "\n" + (it.get("text") or ""))[:2000])
                     for it in items]
            scores = ce.predict(pairs)
            for it, s in zip(items, scores):
                it["score"] = float(s)
            return sorted(items, key=lambda it: it["score"], reverse=True)[:k]
        except Exception as exc:  # noqa: BLE001
            logger.warning("rerank failed: %s", exc)
            return items[:k]

    def recall(self, query: str, *, kind: str | None = None, design: str | None = None,
               k: int = 6, hybrid: bool | None = None, rerank: bool | None = None) -> list[dict]:
        """Retrieve the top-k knowledge items for `query` (optionally filtered by kind/design),
        each with its title/source/text + MinIO object_key. Pipeline:

          dense (pgvector) + lexical (full-text)  →  Reciprocal Rank Fusion  →  cross-encoder rerank

        Hybrid retrieval + reranking sharply raises the relevance of the FEW chunks fed to the
        small-context local model, so each context token carries more signal. Both stages degrade
        gracefully: no FTS → dense-only; no reranker → fusion order. Toggle with ANOA_RAG_HYBRID
        / ANOA_RAG_RERANK (or the per-call args)."""
        if not (self._db_ready and (query or "").strip() and self._ensure_vector()):
            return []
        hybrid = _env_on("ANOA_RAG_HYBRID", True) if hybrid is None else hybrid
        rerank = _env_on("ANOA_RAG_RERANK", True) if rerank is None else rerank
        try:
            # Retrieve BROAD (cheap) so fusion + rerank have a real pool to choose from.
            n = max(k * 6, 30)
            dense = self._dense_candidates(query, kind, design, n)
            if hybrid:
                lex = self._lexical_candidates(query, kind, design, n)
                fused = _rrf_fuse([dense, lex]) if (dense or lex) else []
            else:
                fused = dense
            if not fused:
                return []
            if rerank:
                return self._rerank(query, fused[: max(k * 8, 40)], k)
            return fused[:k]
        except Exception as exc:  # noqa: BLE001
            logger.warning("recall failed: %s", exc)
            return []

    # --- bulk ingestion ----------------------------------------------------
    def ingest_file(self, path, *, design: str = "", source: str = "",
                    kind: str | None = None) -> str | None:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return None
        kind = kind or _kind_for(p)
        ext = p.suffix.lower()
        okey = f"anoa/{design or 'misc'}/{p.name}"
        if ext in _TEXT_EXT:
            try:
                txt = p.read_text(errors="replace")
            except Exception:  # noqa: BLE001
                txt = ""
            return self.remember(kind, txt[:20000], design=design, source=source or str(p),
                                  title=p.name, object_local_path=p, object_key=okey)
        # PDFs and images: EXTRACT their real text (pypdf + OCR fallback) so the row is searchable
        # by CONTENT — not the old "PDF document: paper.pdf" placeholder that recall couldn't use.
        # The original blob still goes to object storage (object_local_path=p).
        note = _BIN_NOTE.get(ext, "binary artifact")
        if ext == ".pdf" or ext in _IMAGE_EXT:
            try:
                from extract import file_to_text
                body = (file_to_text(p) or "").strip()
            except Exception:  # noqa: BLE001
                body = ""
            text = (f"{note}: {p.name}\n\n{body}" if body
                    else f"{note}: {p.name} (design: {design}) — no extractable text")
            return self.remember(kind, text[:20000], design=design, source=source or str(p),
                                  title=p.name, object_local_path=p, object_key=okey)
        return self.remember(kind, f"{note}: {p.name} (design: {design})", design=design,
                              source=source or str(p), title=p.name,
                              object_local_path=p, object_key=okey)

    def ingest_run(self, design_dir, *, design: str = "", query: str = "") -> int:
        """Push every artifact of a finished design (config, netlist, TB, glayout script,
        sim logs, notes, GDS, references, uploads) into the store, plus a one-line 'design'
        summary for recall."""
        if not self.enabled:
            return 0
        d = Path(design_dir)
        design = design or d.name
        patterns = ["config/*.json", "netlist/*.sp", "netlist/*.spice", "tb/*.sp",
                    "layout/*.py", "layout/*.gds", "layout/*.svg", "sim/*.log", "sim/metrics.json",
                    "*.md", "design_notes.md", "result.md", "context/*.md",
                    "context/uploads/*"]
        seen, n = set(), 0
        for pat in patterns:
            for p in d.glob(pat):
                if p.is_file() and p not in seen and "runs" not in p.parts:
                    seen.add(p)
                    if self.ingest_file(p, design=design, source=f"run:{d.name}"):
                        n += 1
        if query:
            self.remember("design",
                          f"Design: {query}\nArtifacts: " + ", ".join(sorted(p.name for p in seen)),
                          design=design, source=f"run:{d.name}", title=query[:120], tags="design")
        return n

    def ingest_corpus(self, root) -> int:
        """Bulk-load a reference corpus (e.g. examples/analog_designs/) into the store."""
        if not self.enabled:
            return 0
        root = Path(root)
        allow = _TEXT_EXT | set(_BIN_NOTE)
        n = 0
        for p in root.rglob("*"):
            if (p.is_file() and p.suffix.lower() in allow
                    and "runs" not in p.parts and ".git" not in p.parts):
                if self.ingest_file(p, design=p.parent.name,
                                    source=f"corpus:{p.relative_to(root)}"):
                    n += 1
        return n

    # --- seed: ship the knowledge with the repo ----------------------------
    def export_seed(self, seed_dir=SEED_DIR) -> int:
        """Dump the WHOLE store to a committed seed: every knowledge row (incl. its
        embedding) to rows.jsonl.gz + every object-storage blob to blobs/. Commit this
        so a fresh clone boots with a populated DB + bucket (an empty store hurts the
        agent). Returns the number of rows exported."""
        if not self._db_ready:
            return 0
        seed_dir = Path(seed_dir)
        blobs = seed_dir / "blobs"
        blobs.mkdir(parents=True, exist_ok=True)
        from sqlalchemy import text as sqltext
        n = 0
        with gzip.open(seed_dir / "rows.jsonl.gz", "wt", encoding="utf-8") as fh, \
                self._engine.connect() as conn:
            rows = conn.execute(sqltext(
                "SELECT id, kind, design, source, title, text, object_key, tags, meta, "
                "       embedding::text AS embedding FROM knowledge")).mappings()
            seen_keys = set()
            for r in rows:
                rec = dict(r)
                meta = rec.get("meta")
                rec["meta"] = meta if isinstance(meta, (dict, type(None))) else json.loads(meta)
                fh.write(json.dumps(rec) + "\n")
                n += 1
                key = rec.get("object_key")
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    blob = self.get_object(key)
                    if blob is not None:
                        (blobs / _blob_filename(key)).write_bytes(blob)
        logger.info("Exported %d knowledge rows + blobs to %s", n, seed_dir)
        return n

    def import_seed(self, seed_dir=SEED_DIR) -> int:
        """Load a committed seed into Postgres (+ MinIO). Uses the stored embeddings —
        no re-embedding, so it's fast and needs no model. Returns rows imported."""
        seed_dir = Path(seed_dir)
        rows_file = seed_dir / "rows.jsonl.gz"
        if not (self._db_ready and rows_file.exists()):
            return 0
        from sqlalchemy import text as sqltext
        blobs = seed_dir / "blobs"
        n = 0
        try:
            with gzip.open(rows_file, "rt", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    emb = rec.get("embedding")
                    if isinstance(emb, list):
                        emb = "[" + ",".join(str(x) for x in emb) + "]"
                    if not self._vec_ready and emb:
                        # derive the column dim from the seed vector (no model load)
                        dim = emb.count(",") + 1
                        self._ensure_vector(dim=dim)
                    with self._engine.begin() as conn:
                        conn.execute(sqltext("""
                            INSERT INTO knowledge
                              (id, kind, design, source, title, text, object_key, tags, meta,
                               embedding, created_at)
                            VALUES
                              (:id, :kind, :design, :source, :title, :text, :object_key, :tags,
                               CAST(:meta AS JSONB), CAST(:emb AS vector), now())
                            ON CONFLICT (id) DO NOTHING
                        """), {
                            "id": rec["id"], "kind": rec.get("kind"), "design": rec.get("design"),
                            "source": rec.get("source"), "title": rec.get("title"),
                            "text": rec.get("text"), "object_key": rec.get("object_key"),
                            "tags": rec.get("tags"), "meta": json.dumps(rec.get("meta") or {}),
                            "emb": emb,
                        })
                    key = rec.get("object_key")
                    if key and self._s3_ready:
                        bf = blobs / _blob_filename(key)
                        if bf.exists():
                            try:
                                self._s3.put_object(Bucket=self.s3_bucket, Key=key,
                                                    Body=bf.read_bytes())
                            except Exception:  # noqa: BLE001
                                pass
                    n += 1
            logger.info("Imported %d knowledge rows from seed %s", n, seed_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("import_seed failed: %s", exc)
        return n

    def seed_if_empty(self) -> int:
        """If the store is empty but a committed seed exists, load it. Called at startup
        so a fresh clone is never empty."""
        if not self._db_ready:
            return 0
        if (self.stats().get("total") or 0) > 0:
            return 0
        if not SEED_ROWS.exists():
            return 0
        return self.import_seed()

    # --- admin: browse / fetch / delete ------------------------------------
    def list_items(self, *, kind: str | None = None, design: str | None = None,
                   limit: int = 200) -> list[dict]:
        """List rows (metadata only, no embedding) for browsing, newest first."""
        if not self._db_ready:
            return []
        from sqlalchemy import text as sqltext
        conds, params = [], {"limit": int(limit)}
        if kind:
            conds.append("kind = :kind")
            params["kind"] = kind
        if design:
            conds.append("design = :design")
            params["design"] = design
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        sql = ("SELECT id, kind, design, title, source, object_key, "
               "(embedding IS NOT NULL) AS has_vector, created_at "
               f"FROM knowledge {where} ORDER BY created_at DESC NULLS LAST, id LIMIT :limit")
        with self._engine.begin() as conn:
            return [dict(r) for r in conn.execute(sqltext(sql), params).mappings().all()]

    def get(self, item_id: str) -> dict | None:
        """Fetch one full row (incl. its text) by id."""
        if not self._db_ready:
            return None
        from sqlalchemy import text as sqltext
        with self._engine.begin() as conn:
            row = conn.execute(sqltext(
                "SELECT id, kind, design, source, title, text, object_key, tags, meta, "
                "created_at FROM knowledge WHERE id = :id"), {"id": item_id}).mappings().first()
        return dict(row) if row else None

    def delete(self, item_id: str) -> bool:
        """Delete one item: its blob (MinIO) then its row (Postgres)."""
        if not self._db_ready:
            return False
        row = self.get(item_id)
        if row and row.get("object_key") and self._s3_ready:
            try:
                self._s3.delete_object(Bucket=self.s3_bucket, Key=row["object_key"])
            except Exception:  # noqa: BLE001
                pass
        from sqlalchemy import text as sqltext
        with self._engine.begin() as conn:
            res = conn.execute(sqltext("DELETE FROM knowledge WHERE id = :id"),
                               {"id": item_id})
        return (res.rowcount or 0) > 0

    def delete_where(self, *, kind: str | None = None, design: str | None = None,
                     exclude_kinds: "list[str] | None" = None) -> int:
        """Bulk-delete every item matching kind and/or design (+ their blobs). Requires
        at least one filter — refuses to wipe the whole store by accident. `exclude_kinds`
        PRESERVES those kinds (e.g. ['fix']) — used when deleting a chat's design so the
        learned error→fix lessons stay in the durable store even after the chat is gone."""
        if not self._db_ready or not (kind or design):
            return 0
        from sqlalchemy import text as sqltext
        conds, params = [], {}
        if kind:
            conds.append("kind = :kind")
            params["kind"] = kind
        if design:
            conds.append("design = :design")
            params["design"] = design
        for i, k in enumerate(exclude_kinds or []):
            conds.append(f"kind <> :xk{i}")
            params[f"xk{i}"] = k
        where = " AND ".join(conds)
        with self._engine.begin() as conn:
            keys = [r[0] for r in conn.execute(sqltext(
                f"SELECT object_key FROM knowledge WHERE {where} AND object_key IS NOT NULL"),
                params).all()]
            res = conn.execute(sqltext(f"DELETE FROM knowledge WHERE {where}"), params)
        if self._s3_ready:
            for k in keys:
                try:
                    self._s3.delete_object(Bucket=self.s3_bucket, Key=k)
                except Exception:  # noqa: BLE001
                    pass
        return res.rowcount or 0

    def wipe(self) -> int:
        """DELETE EVERY row + blob — a full store reset. Used by
        scripts/build_knowledge_seed.py to rebuild the seed from scratch."""
        if not self._db_ready:
            return 0
        from sqlalchemy import text as sqltext
        with self._engine.begin() as conn:
            keys = [r[0] for r in conn.execute(sqltext(
                "SELECT object_key FROM knowledge WHERE object_key IS NOT NULL")).all()]
            res = conn.execute(sqltext("DELETE FROM knowledge"))
        if self._s3_ready:
            for k in keys:
                try:
                    self._s3.delete_object(Bucket=self.s3_bucket, Key=k)
                except Exception:  # noqa: BLE001
                    pass
        return res.rowcount or 0

    def list_objects(self, prefix: str = "") -> list[dict]:
        """List MinIO objects (key + size), handling pagination."""
        if not self._s3_ready:
            return []
        out, token = [], None
        try:
            while True:
                kw = {"Bucket": self.s3_bucket, "Prefix": prefix}
                if token:
                    kw["ContinuationToken"] = token
                r = self._s3.list_objects_v2(**kw)
                out += [{"key": o["Key"], "size": o["Size"]} for o in r.get("Contents", [])]
                if not r.get("IsTruncated"):
                    break
                token = r.get("NextContinuationToken")
        except Exception:  # noqa: BLE001
            pass
        return out

    # --- introspection -----------------------------------------------------
    def stats(self) -> dict:
        if not self._db_ready:
            return {}
        try:
            from sqlalchemy import text as sqltext
            with self._engine.begin() as conn:
                total = conn.execute(sqltext("SELECT count(*) FROM knowledge")).scalar()
                by_kind = dict(conn.execute(sqltext(
                    "SELECT kind, count(*) FROM knowledge GROUP BY kind")).all())
            return {"total": int(total or 0), "by_kind": by_kind}
        except Exception:  # noqa: BLE001
            return {}


_store: MemoryStore | None = None


def get_memory() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
        try:
            seeded = _store.seed_if_empty()      # fresh clone? load the committed seed
            if seeded:
                logger.info("Seeded knowledge store with %d items from the repo.", seeded)
        except Exception as exc:  # noqa: BLE001
            logger.warning("seed_if_empty failed: %s", exc)
    return _store


if __name__ == "__main__":  # tiny CLI: python memory_store.py <cmd> [args]
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    mem = MemoryStore()                      # bypass auto-seed for explicit ops
    if cmd == "stats":
        print(mem.stats())
    elif cmd == "export":
        print("exported rows:", mem.export_seed())
    elif cmd == "import":
        print("imported rows:", mem.import_seed())
    elif cmd == "ingest-corpus":
        root = sys.argv[2] if len(sys.argv) > 2 else str(REPO_ROOT / "examples" / "analog_designs")
        print(f"ingesting corpus {root} …")
        print("ingested files:", mem.ingest_corpus(root))
    elif cmd == "ingest-run":
        print("ingested files:", mem.ingest_run(sys.argv[2]))
    elif cmd == "recall":
        for r in mem.recall(" ".join(sys.argv[2:]) or "ota", k=8):
            print(f"  {r['score']:.3f} [{r['kind']}] {r['title']} (design={r['design']})")
    else:
        print(f"unknown command: {cmd}")
        print("usage: memory_store.py [stats|export|import|ingest-corpus [dir]|ingest-run <dir>|recall <query>]")
