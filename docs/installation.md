# Installation Guide

## Prerequisites

| Tool | Required | Install |
|------|----------|---------|
| Python 3.13+ | ✅ | `sudo apt install python3.13` or pyenv |
| `uv` | ✅ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| ngspice | ✅ | `sudo apt install ngspice` |
| KLayout | ✅ | installed via pip (`klayout>=0.28`) |
| Magic 8.3.411+ | ✅ DRC/LVS | build from source (see below) |
| Netgen 1.5.x | ✅ LVS | build from source (see below) |
| openEMS | optional | `sudo apt install openems python3-openems` |

> Ubuntu 22.04 APT `magic` (8.3.105) and `netgen` (mesh tool, wrong package) are too old. Both must be built from source.

## Step 1 — Clone

```bash
git clone https://github.com/adeirman46/Gelochip.git
cd Gelochip
```

## Step 2 — Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

## Step 3 — Create venv

```bash
uv sync --extra ml --extra notebooks
```

## Step 4 — Build Magic and Netgen from source

```bash
sudo apt install -y tcl-dev tk-dev libx11-dev libncurses-dev gcc make

# Magic 8.3.644
mkdir -p /tmp/magic_build && cd /tmp/magic_build
curl -L -o magic.tar.gz "https://github.com/RTimothyEdwards/magic/archive/refs/tags/8.3.644.tar.gz"
tar xzf magic.tar.gz && cd magic-8.3.644
./configure --prefix="/path/to/Gelochip/.venv" --without-cairo --without-opengl
make -j$(nproc) && make install

# Netgen 1.5.272
mkdir -p /tmp/netgen_build && cd /tmp/netgen_build
curl -L -o netgen.tar.gz "https://github.com/RTimothyEdwards/netgen/archive/refs/tags/1.5.272.tar.gz"
tar xzf netgen.tar.gz && cd netgen-1.5.272
./configure --prefix="/path/to/Gelochip/.venv" --with-tcl=/usr/lib/tcl8.6 --with-tk=/usr/lib/tk8.6
make -j$(nproc) && make install

# Verify
.venv/bin/magic --version   # → 8.3.644
.venv/bin/netgen --version  # → Netgen 1.5.272
```

## Step 5 — Configure LLM

```bash
cp .env.example .env
nano .env
```

### Option A — Local (Ollama, free, 8 GB VRAM)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:8b
```

```dotenv
OLLAMA_MODEL=qwen3:8b
```

### Option B — Cloud API

```dotenv
ANTHROPIC_API_KEY=sk-ant-...
# GOOGLE_API_KEY=AIza...
# OPENAI_API_KEY=sk-...
```

## Step 6 — Set up gf180 PDK

```bash
# Recommended: volare (lightweight)
uv run pip install volare
uv run volare enable --pdk gf180mcu --version 0.0.1

# Alternative: IIC-OSIC-TOOLS Docker (all tools pre-installed)
# docker pull hpretl/iic-osic-tools
```

## openEMS (PixelatedRF notebooks only)

openEMS is used in `notebooks/pixelatedRF/04_simulate.ipynb` for FDTD simulation. The apt `python3-openems` is compiled for Python 3.10 only — build from source for the Python 3.13 venv:

```bash
sudo apt install -y cmake libhdf5-dev libtinyxml2-dev libboost-dev libfparser-dev patchelf

# 1. Build CSXCAD C++ (use commit 3b68dfb — API compatible with openEMS HEAD)
git clone https://github.com/thliebig/CSXCAD.git /tmp/CSXCAD_src
cd /tmp/CSXCAD_src && git checkout 3b68dfb
cmake -S . -B /tmp/csxcad_build -DCMAKE_INSTALL_PREFIX="$PWD/.venv" -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/csxcad_build -j$(nproc) && cmake --install /tmp/csxcad_build

# 2. Build CSXCAD Python bindings
CSXCAD_LIB_DIR=".venv/lib" CSXCAD_INC_DIR=".venv/include" \
  .venv/bin/python /tmp/CSXCAD_src/python/setup.py install

# 3. Build openEMS C++
git clone https://github.com/thliebig/openEMS.git /tmp/openEMS_src
cmake -S /tmp/openEMS_src -B /tmp/openems_build \
  -DCMAKE_INSTALL_PREFIX="$PWD/.venv" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS="-I$PWD/.venv/include/CSXCAD" \
  -DCSXCAD_LIBRARIES="$PWD/.venv/lib/libCSXCAD.so" \
  -DCSXCAD_INCLUDE_DIR="$PWD/.venv/include" -DWITH_MPI=OFF
cmake --build /tmp/openems_build -j$(nproc) && cmake --install /tmp/openems_build

# 4. Build openEMS Python bindings + h5py
OPENEMS_LIB_DIR=".venv/lib" OPENEMS_INC_DIR=".venv/include" \
CSXCAD_LIB_DIR=".venv/lib" CSXCAD_INC_DIR=".venv/include" \
  .venv/bin/python /tmp/openEMS_src/python/setup.py install
uv add h5py

# 5. Fix RPATH (so .so files find each other without LD_LIBRARY_PATH)
VENV_LIB="$PWD/.venv/lib"
for so in $VENV_LIB/python3.13/site-packages/openEMS/*.so \
          $VENV_LIB/python3.13/site-packages/CSXCAD/*.so \
          $VENV_LIB/libopenEMS.so $VENV_LIB/libCSXCAD.so $VENV_LIB/libnf2ff.so; do
  patchelf --add-rpath "$VENV_LIB" "$so"
done

# Verify
.venv/bin/python -c "import openEMS, CSXCAD; print('openEMS OK')"
```
