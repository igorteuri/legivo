"""Operações de imagem leves (Pillow + NumPy), sem OpenCV."""
from __future__ import annotations
import numpy as np
from PIL import Image


def resize(img: np.ndarray, s: float | None = None, size: tuple[int, int] | None = None) -> np.ndarray:
    """Redimensiona uma imagem em tons de cinza. `s` = fator; `size` = (largura, altura)."""
    h, w = img.shape[:2]
    nw, nh = size if size else (max(1, round(w * s)), max(1, round(h * s)))
    if (nw, nh) == (w, h):
        return img
    filt = Image.LANCZOS if (nw < w or nh < h) else Image.BICUBIC
    return np.array(Image.fromarray(img).resize((nw, nh), filt))


def rotate_cw(img: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.rot90(img, -1))
