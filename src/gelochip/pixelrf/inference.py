"""
PixelatedRF inference: forward surrogate + Transformer cross-attention inverse cVAE.
Model classes must match notebooks/pixelatedRF/02_train.ipynb exactly.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
GRID_DIM = 12
N_FREQ = 81
K_SAMPLES = 8


# ── Forward Surrogate building blocks ─────────────────────────────────────────

class ResBlock1D(nn.Module):
    def __init__(self, dim: int, dropout: float = 0.1):
        super().__init__()
        self.norm = nn.LayerNorm(dim)
        self.ff = nn.Sequential(
            nn.Linear(dim, dim * 2), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(dim * 2, dim), nn.Dropout(dropout),
        )
    def forward(self, x): return x + self.ff(self.norm(x))


class SEBlock(nn.Module):
    def __init__(self, ch: int, r: int = 8):
        super().__init__()
        self.fc = nn.Sequential(
            nn.AdaptiveAvgPool2d(1), nn.Flatten(),
            nn.Linear(ch, max(ch // r, 4)), nn.GELU(),
            nn.Linear(max(ch // r, 4), ch), nn.Sigmoid(),
        )
    def forward(self, x): return x * self.fc(x).view(-1, x.size(1), 1, 1)


class SpatialResBlockSE(nn.Module):
    def __init__(self, ch: int, groups: int = 8):
        super().__init__()
        g = min(groups, ch)
        self.block = nn.Sequential(
            nn.Conv2d(ch, ch, 3, padding=1, bias=False), nn.GroupNorm(g, ch), nn.GELU(),
            nn.Conv2d(ch, ch, 3, padding=1, bias=False), nn.GroupNorm(g, ch),
        )
        self.se = SEBlock(ch)
    def forward(self, x): return F.gelu(x + self.se(self.block(x)))


class ForwardSurrogateNet(nn.Module):
    def __init__(self, grid_dim=12, n_freq=81, cnn_ch=48, hidden=512, n_res=3):
        super().__init__()
        self.grid_dim = grid_dim
        self.stage1 = nn.Sequential(
            nn.Conv2d(3, cnn_ch, 3, padding=1, bias=False),
            nn.GroupNorm(min(8, cnn_ch), cnn_ch), nn.GELU(),
            *[SpatialResBlockSE(cnn_ch) for _ in range(n_res)])
        self.down1 = nn.Sequential(
            nn.Conv2d(cnn_ch, cnn_ch*2, 3, stride=2, padding=1, bias=False),
            nn.GroupNorm(min(8, cnn_ch*2), cnn_ch*2), nn.GELU())
        self.stage2 = nn.Sequential(*[SpatialResBlockSE(cnn_ch*2) for _ in range(n_res)])
        self.down2 = nn.Sequential(
            nn.Conv2d(cnn_ch*2, cnn_ch*4, 3, stride=2, padding=1, bias=False),
            nn.GroupNorm(min(8, cnn_ch*4), cnn_ch*4), nn.GELU())
        self.stage3 = nn.Sequential(*[SpatialResBlockSE(cnn_ch*4) for _ in range(n_res)])
        ms_dim = cnn_ch + cnn_ch*2 + cnn_ch*4*3*3
        self.head = nn.Sequential(
            nn.Linear(ms_dim, hidden), nn.GELU(), nn.Dropout(0.10),
            *[ResBlock1D(hidden, dropout=0.10) for _ in range(6)],
            nn.Linear(hidden, n_freq))

    def _add_coords(self, x):
        B, _, H, W = x.shape
        rows = torch.linspace(-1, 1, H, device=x.device).view(1,1,H,1).expand(B,1,H,W)
        cols = torch.linspace(-1, 1, W, device=x.device).view(1,1,1,W).expand(B,1,H,W)
        return torch.cat([x, rows, cols], dim=1)

    def forward(self, x):
        if x.dim() == 2:   x = x.view(-1, 1, self.grid_dim, self.grid_dim)
        elif x.dim() == 3: x = x.unsqueeze(1)
        x = self._add_coords(x)
        f1 = self.stage1(x)
        f2 = self.stage2(self.down1(f1))
        f3 = self.stage3(self.down2(f2))
        return self.head(torch.cat([f1.mean((-2,-1)), f2.mean((-2,-1)), f3.flatten(1)], dim=1))


# ── Multi-Choice Learning (MCL) inverse net — K=8 parallel heads ──────────────

class ResMLP(nn.Module):
    def __init__(self, dim: int, mult: int = 2, drop: float = 0.1):
        super().__init__()
        self.norm = nn.LayerNorm(dim)
        self.ff = nn.Sequential(
            nn.Linear(dim, dim * mult), nn.GELU(), nn.Dropout(drop),
            nn.Linear(dim * mult, dim), nn.Dropout(drop),
        )
    def forward(self, x): return x + self.ff(self.norm(x))


class InverseNet(nn.Module):
    """Multi-Choice Learning: K parallel decoders trained with best-of-K loss."""
    def __init__(self, n_freq=81, grid_dim=12, n_heads=8, base_ch=64, hidden=512):
        super().__init__()
        self.grid_dim = grid_dim
        self.n_heads  = n_heads
        self.latent_dim = 0          # no latent z (kept for API compat)
        c = base_ch
        s11_dim = c * 4

        self.s11_enc = nn.Sequential(
            nn.Conv1d(1,   c,   7, padding=3,           bias=False), nn.GroupNorm(8, c),   nn.GELU(),
            nn.Conv1d(c,   c*2, 5, padding=2, stride=2, bias=False), nn.GroupNorm(8, c*2), nn.GELU(),
            nn.Conv1d(c*2, c*2, 3, padding=1,           bias=False), nn.GroupNorm(8, c*2), nn.GELU(),
            nn.Conv1d(c*2, c*4, 5, padding=2, stride=2, bias=False), nn.GroupNorm(8, c*4), nn.GELU(),
            nn.Conv1d(c*4, c*4, 3, padding=1,           bias=False), nn.GroupNorm(8, c*4), nn.GELU(),
            nn.AdaptiveAvgPool1d(1), nn.Flatten(),
        )
        self.trunk = nn.Sequential(
            nn.Linear(s11_dim, hidden), nn.LayerNorm(hidden), nn.GELU(),
            ResMLP(hidden), ResMLP(hidden), ResMLP(hidden),
        )
        self.heads = nn.ModuleList([
            nn.Sequential(
                nn.Linear(hidden, hidden), nn.LayerNorm(hidden), nn.GELU(),
                ResMLP(hidden),
                nn.Linear(hidden, grid_dim * grid_dim),
            ) for _ in range(n_heads)
        ])

    def _all_logits(self, s11):
        s_h = self.s11_enc(s11.unsqueeze(1))
        t   = self.trunk(s_h)
        logits = torch.stack([h(t) for h in self.heads], dim=1)
        return logits.view(-1, self.n_heads, self.grid_dim, self.grid_dim)

    def decode(self, z, s11, tau=None):
        logits = self._all_logits(s11)
        return torch.sigmoid(logits[:, 0]), logits[:, 0]

    def sample(self, s11, k=None, tau=None):
        with torch.no_grad():
            logits = self._all_logits(s11)
            if logits.shape[0] == 1:
                return (logits[0] > 0).float()           # (K, H, W)
            return (logits > 0).float()


# ── Model state ────────────────────────────────────────────────────────────────

_fwd_model: ForwardSurrogateNet | None = None
_inv_model: InverseNet | None = None
_Y_mean: torch.Tensor | None = None
_Y_std:  torch.Tensor | None = None
_CLIP_Z: float = 5.0
_freqs_ghz: np.ndarray | None = None


def _repo_root() -> Path:
    # src/gelochip/pixelrf/inference.py → repo root is 4 levels up.
    return Path(__file__).resolve().parents[3]


def _default_model_dir() -> Path:
    # Consolidated model location: <repo>/models/pixelatedrf
    primary = _repo_root() / "models" / "pixelatedrf"
    if primary.exists():
        return primary
    # legacy fallbacks
    for cand in (Path(__file__).resolve().parent / "models",
                 _repo_root() / "notebooks" / "pixelatedRF" / "models"):
        if cand.exists():
            return cand
    raise FileNotFoundError("Cannot locate pixelatedrf model directory (models/pixelatedrf)")


def load_models(model_dir: Path | str | None = None) -> None:
    global _fwd_model, _inv_model, _Y_mean, _Y_std, _CLIP_Z, _freqs_ghz

    md = Path(model_dir) if model_dir else _default_model_dir()
    # normalization stats live with the datasets now: data/pixelatedrf/
    norm_path = _repo_root() / "data" / "pixelatedrf" / "y_norm_stats.npz"
    if not norm_path.exists():
        norm_path = md.parent / "y_norm_stats.npz"   # legacy fallback

    _fwd_model = ForwardSurrogateNet(GRID_DIM, N_FREQ, cnn_ch=48, hidden=512, n_res=3).to(DEVICE)
    _fwd_model.load_state_dict(torch.load(md / "forward_model.pt", map_location=DEVICE))
    _fwd_model.eval()

    ckpt_path = md / "inverse_model.pt"
    if not ckpt_path.exists():
        raise FileNotFoundError(f"inverse_model.pt not found in {md}")

    ckpt  = torch.load(ckpt_path, map_location=DEVICE)
    state = ckpt.get("best_model_state", ckpt) if isinstance(ckpt, dict) else ckpt

    _inv_model = InverseNet(N_FREQ, GRID_DIM, n_heads=8, base_ch=64, hidden=512).to(DEVICE)
    _inv_model.load_state_dict(state)
    _inv_model.eval()

    norm = np.load(norm_path)
    _Y_mean = torch.tensor(norm["Y_mean"], dtype=torch.float32)
    _Y_std  = torch.tensor(norm["Y_std"],  dtype=torch.float32)
    _CLIP_Z = float(norm["clip_z"])
    _freqs_ghz = np.linspace(1.0, 10.0, N_FREQ)

    print(f"[pixelrf] Forward + InverseNet(Transformer xattn) loaded on {DEVICE}")


class PredictResult(NamedTuple):
    layout: list[list[int]]
    surrogate_s11: list[float]
    rmse_db: float
    fill: float
    freqs_ghz: list[float]


def predict(s11_db: list[float], k: int = K_SAMPLES) -> PredictResult:
    if _inv_model is None:
        load_models()

    target   = torch.tensor(s11_db, dtype=torch.float32).unsqueeze(0)
    target_n = ((target - _Y_mean) / _Y_std).clamp(-_CLIP_Z, _CLIP_Z).to(DEVICE)

    with torch.no_grad():
        candidates = _inv_model.sample(target_n, k=k)
        bins       = (candidates > 0.5).float()
        pred_n     = _fwd_model(bins).cpu()
        tgt_n_cpu  = target_n.cpu()
        best_k     = ((pred_n - tgt_n_cpu)**2).mean(-1).argmin().item()
        pred_db    = (pred_n[best_k] * _Y_std.squeeze() + _Y_mean.squeeze()).numpy()
        layout_np  = bins[best_k].cpu().numpy()

    rmse = float(np.sqrt(((pred_db - np.array(s11_db))**2).mean()))
    return PredictResult(
        layout=layout_np.astype(int).tolist(),
        surrogate_s11=pred_db.tolist(),
        rmse_db=rmse,
        fill=float(layout_np.mean()),
        freqs_ghz=_freqs_ghz.tolist(),
    )
