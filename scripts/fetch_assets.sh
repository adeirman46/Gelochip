#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Download the large assets that are NOT in git (model weights + EM datasets).
# These are git-ignored so `git push` never hits GitHub's 100 MB file limit.
#
#   1. Edit DRIVE_URL below with your Google Drive share link.
#   2. Run:  ./scripts/fetch_assets.sh
#
# Expected layout after download:
#   models/pixelatedrf/{forward_model,inverse_model,*_resume}.pt   (EM models)
#   data/pixelatedrf/{antenna_dataset.mat, data_split.npz}         (EM dataset)
#
# Note: the ChromaDB vector store is NOT downloaded — it auto-rebuilds on the
# first `./scripts/run.sh kaizen` launch from the datasets in data/.
# ─────────────────────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")/.."

# TODO: replace with your Google Drive folder/file link, then uncomment the gdown call.
DRIVE_URL="https://drive.google.com/REPLACE_ME"

mkdir -p models/pixelatedrf data/pixelatedrf

echo "[assets] target Drive URL: $DRIVE_URL"
if [ "$DRIVE_URL" = "https://drive.google.com/REPLACE_ME" ]; then
  echo "[assets] ✗ Set DRIVE_URL in scripts/fetch_assets.sh first."
  echo "         Then this will fetch into models/pixelatedrf/ and data/pixelatedrf/."
  exit 1
fi

# Requires gdown:  .venv/bin/python -m pip install gdown   (or use rclone / manual)
# .venv/bin/python -m gdown --folder "$DRIVE_URL" -O ./_assets_tmp
# … then move files into models/pixelatedrf/ and data/pixelatedrf/ …
echo "[assets] (uncomment the gdown line above once DRIVE_URL is set)"
