#!/usr/bin/env bash
# Setup PDKs for Gelochip
set -e

PDK_ROOT="${PDK_ROOT:-$HOME/pdks}"
mkdir -p "$PDK_ROOT"

echo "Installing sky130 PDK via volare..."
uv run pip install volare
uv run volare enable --pdk sky130 --version bdc9412

echo "Installing gf180 PDK via volare..."
uv run volare enable --pdk gf180mcu --version 0.0.1

echo "PDKs installed at: $PDK_ROOT"
echo "Add to .env:"
echo "  PDK_ROOT=$PDK_ROOT"
