# Running Gelochip Studio with Docker

Everything — the EDA tools (magic, netgen, ngspice, klayout), the gf180 PDK,
the RAG agent, the ChromaDB knowledge, the embedding model, and the React UI —
is packaged into one image. The only separate piece is the LLM, which runs in
the official `ollama` container alongside it.

## TL;DR

```bash
docker compose up --build
```

Then open:

- **http://localhost:8090** — Gelochip Studio (the RAG agent)
- **http://localhost:8001** — PixelatedRF Designer (S₁₁ → inverse-designed GDS)

That's it. No VNC, no manual tool installs, no PDK setup. It's a normal web app,
so you just expose the HTTP port and browse to it.

### What's bundled in the image

Self-contained — the image carries everything except the LLM (which runs in the
`ollama` sidecar):

- Ubuntu + EDA tools (magic, netgen, ngspice, klayout) + gf180 PDK
- all datasets (`data/`), including the PixelatedRF EM datasets
- the offline embedding model + prebuilt ChromaDB collections
- the **PixelatedRF inference weights** (`forward_model.pt`, `inverse_model.pt`)
  and the layoutRL PPO policy
- the FastAPI backend + compiled React SPA

> The large `*_resume.pt` files (~610 MB) are **training-resume checkpoints** and
> are intentionally left out — nothing at runtime needs them. To resume training,
> copy them into `models/pixelatedrf/`.

---

## What happens on first `up`

1. **`ollama`** starts the LLM server.
2. **`ollama-pull`** downloads the agent model (`qwen3.5:9b`, ~6 GB) into a named
   volume, then exits. This is the only large one-time download.
3. **`studio`** builds the app image (EDA tools compiled from source, gf180 PDK
   installed, Python deps, React SPA built, ChromaDB collections prebuilt, the
   embedding model + PixelatedRF weights baked in) and serves it on port 8090.
4. **`pixelrf`** reuses that same image (different entrypoint) and serves the
   PixelatedRF Designer on port 8001.

The first build takes a while (magic + netgen compile from source). Subsequent
`up`s are instant — the model, image layers, and volumes are all cached.

## Persistence

Three named volumes survive restarts:

| Volume            | Holds                                             |
| ----------------- | ------------------------------------------------- |
| `ollama`          | the pulled LLM weights                            |
| `studio-outputs`  | generated GDS/PNG/SPICE + chat history (`sessions.db`) |
| `studio-chroma`   | the RAG collections (they grow as the agent learns) |

Wipe everything with `docker compose down -v`.

## Configuration

Override via environment (or a `.env` file next to `docker-compose.yml`):

| Variable                 | Default       | Meaning                                  |
| ------------------------ | ------------- | ---------------------------------------- |
| `KAIZEN_LLM_MODEL`       | `qwen3.5:9b`  | Ollama model the agent uses (pull + run) |
| `KAIZEN_ALLOWED_ORIGINS` | `*`           | CORS origins (set to your domain in prod) |
| `KAIZEN_MAX_CONCURRENT`  | `2`           | concurrent prompt→GDS jobs               |

## GPU (much faster generation)

Generation runs on CPU by default (works everywhere). To use an NVIDIA GPU:

1. Install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) on the host, then verify:
   ```bash
   docker run --rm --gpus all ubuntu nvidia-smi
   ```
2. Bring the stack up with the GPU override:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.gpu.yml up
   ```

Ollama offloads as many model layers as fit in VRAM (the rest stay on CPU), so
this speeds things up even on smaller cards (e.g. an 8 GB laptop GPU runs a good
chunk of `qwen3.5:9b` on-device). The toolkit is a per-host requirement — it
can't be baked into the image, so each user installs it once on their machine.

## Should I upload the image, or what?

You have three options — pick based on your audience:

1. **Ship the repo (recommended).** Commit the `Dockerfile`, `docker-compose.yml`,
   and `requirements-app.txt`. Users clone and run `docker compose up --build`.
   Nothing to host; the image builds locally and the model auto-pulls.

2. **Publish a prebuilt image** so users skip the ~20-minute build:

   ```bash
   docker build -t <youruser>/gelochip-studio:latest .
   docker push <youruser>/gelochip-studio:latest
   ```

   Then have them point `docker-compose.yml`'s `studio` service at
   `image: <youruser>/gelochip-studio:latest` instead of `build: .`.

3. **Air-gapped / hand-off as a file:**

   ```bash
   docker compose build
   docker save gelochip-studio ollama/ollama | gzip > gelochip-studio.tar.gz
   # recipient:
   docker load < gelochip-studio.tar.gz && docker compose up
   ```

   Note: the LLM weights live in the `ollama` volume, not the image, so an
   air-gapped recipient also needs the model pulled (or the volume exported).

## Running standalone (without compose)

If you already run Ollama on the host:

```bash
docker build -t gelochip-studio .
docker run --rm -p 8090:8090 \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  gelochip-studio
```

## Troubleshooting

- **`health` badge is amber/red** → the model isn't pulled yet. Watch
  `docker compose logs -f ollama-pull`; the badge goes green once it finishes.
- **Slow first generation** → the model loads into RAM on the first call
  (~30–90 s). It's fast afterwards. Use a GPU to speed this up.
- **Rebuild after code changes** → `docker compose up --build`.
