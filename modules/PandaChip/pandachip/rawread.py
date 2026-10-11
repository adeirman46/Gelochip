"""Minimal ngspice rawfile reader (binary and ASCII) used for waveform checks."""

from __future__ import annotations

import struct
from pathlib import Path


def read_raw(path: str | Path) -> dict:
    """Parse an ngspice rawfile into {"vectors": {name: [float, ...]}, "meta": {...}}.

    Complex vectors (AC) are returned as magnitude.
    """
    data = Path(path).read_bytes()
    header_end = data.find(b"Binary:\n")
    ascii_values = False
    if header_end < 0:
        header_end = data.find(b"Values:\n")
        if header_end < 0:
            raise ValueError("Not an ngspice rawfile: no Binary:/Values: marker")
        ascii_values = True
        payload = data[header_end + len(b"Values:\n"):]
    else:
        payload = data[header_end + len(b"Binary:\n"):]

    meta: dict = {}
    names: list[str] = []
    for line in data[:header_end].decode("utf-8", "replace").splitlines():
        low = line.lower()
        if low.startswith("title:"):
            meta["title"] = line.split(":", 1)[1].strip()
        elif low.startswith("plotname:"):
            meta["plotname"] = line.split(":", 1)[1].strip()
        elif low.startswith("flags:"):
            meta["flags"] = line.split(":", 1)[1].strip()
        elif low.startswith("no. variables:"):
            meta["n_vars"] = int(line.split(":", 1)[1])
        elif low.startswith("no. points:"):
            meta["n_points"] = int(line.split(":", 1)[1])
        elif line.startswith(("\t", " ")) and len(line.split()) >= 2 and "n_vars" in meta:
            parts = line.split()
            if parts[0].isdigit() and len(names) < meta["n_vars"]:
                names.append(parts[1])

    n_vars, n_points = meta["n_vars"], meta["n_points"]
    is_complex = "complex" in meta.get("flags", "")
    vectors: dict[str, list[float]] = {n: [] for n in names}

    if ascii_values:
        tokens = payload.decode("utf-8", "replace").split()
        idx = 0
        for _ in range(n_points):
            idx += 1  # point index
            for name in names:
                tok = tokens[idx]
                idx += 1
                if is_complex and "," in tok:
                    re_s, im_s = tok.split(",")
                    vectors[name].append((float(re_s) ** 2 + float(im_s) ** 2) ** 0.5)
                else:
                    vectors[name].append(float(tok))
    else:
        width = 16 if is_complex else 8
        stride = n_vars * width
        for p in range(n_points):
            base = p * stride
            for i, name in enumerate(names):
                off = base + i * width
                if is_complex:
                    re_v, im_v = struct.unpack_from("<dd", payload, off)
                    vectors[name].append((re_v * re_v + im_v * im_v) ** 0.5)
                else:
                    vectors[name].append(struct.unpack_from("<d", payload, off)[0])

    meta["variables"] = names
    return {"vectors": vectors, "meta": meta}
