"""OCR (reconhecimento de texto) para PDFs que são só imagem.

Usa o RapidOCR (modelos PP-OCRv6 do PaddleOCR, via ONNX Runtime), que roda em CPU, offline,
sem instalar nada no sistema. As linhas reconhecidas viram "spans" com posição e tamanho,
iguais aos que o PDF de texto fornece, e entram no mesmo caminho do EPUB.
"""
from __future__ import annotations
import json
import threading
from pathlib import Path

import numpy as np

_lock = threading.Lock()          # cria o motor uma vez
_run_lock = threading.Lock()      # uma inferência por vez
_engine = None

DEFAULT_DPI = 200                 # resolução da imagem enviada ao OCR (200 = bom equilíbrio)
SECONDS_PER_PAGE = 4.0            # estimativa para avisar o usuário (CPU comum)


def available() -> tuple[bool, str]:
    """O OCR está instalado nesta cópia do programa?"""
    try:
        import rapidocr  # noqa: F401
        import onnxruntime  # noqa: F401
        return True, ""
    except Exception as e:   # pragma: no cover - depende da instalação
        return False, str(e)


def _get_engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr import RapidOCR
            _engine = RapidOCR()
        return _engine


def recognize(img_rgb: np.ndarray) -> list[dict]:
    """Reconhece o texto de uma imagem RGB. Devolve [{box:(x0,y0,x1,y1) em px, text, score}]."""
    eng = _get_engine()
    with _run_lock:
        res = eng(img_rgb, return_word_box=True)
    if res is None or res.txts is None:
        return []
    wres = list(getattr(res, "word_results", None) or [])
    out = []
    for k, (box, text, score) in enumerate(zip(res.boxes, res.txts, res.scores)):
        text = (text or "").strip()
        if not text:
            continue
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        words = []
        if k < len(wres):
            for w in wres[k]:
                wt, _, wb = w[0], w[1], w[2]
                wx, wy = [p[0] for p in wb], [p[1] for p in wb]
                if str(wt).strip():
                    words.append({"t": str(wt), "b": (float(min(wx)), float(min(wy)), float(max(wx)), float(max(wy)))})
        out.append({"box": (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))),
                    "text": text, "score": float(score), "words": words})
    return out


def to_spans(lines: list[dict], dpi: int) -> list[dict]:
    """Converte as linhas do OCR (px) para spans no formato do PyMuPDF (pt): bbox, texto, tamanho."""
    k = 72.0 / dpi
    spans = []
    for l in lines:
        x0, y0, x1, y1 = (v * k for v in l["box"])
        spans.append({"bbox": (x0, y0, x1, y1), "text": l["text"], "size": max(1.0, (y1 - y0) * 0.85),
                      "flags": 0, "font": "ocr"})
    return spans


# ------------------------------------------------------------------ cache em disco
def save_cache(path, dpi: int, pages: dict[int, list[dict]]):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"dpi": dpi, "pages": {str(i): [{"b": list(l["box"]), "t": l["text"], "s": round(l["score"], 3),
                                            "w": [{"t": w["t"], "b": [round(v, 1) for v in w["b"]]} for w in l.get("words", [])]}
                                           for l in ls] for i, ls in pages.items()}}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def load_cache(path) -> tuple[int, dict[int, list[dict]]] | None:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        pages = {int(i): [{"box": tuple(x["b"]), "text": x["t"], "score": x.get("s", 1.0),
                           "words": [{"t": w["t"], "b": tuple(w["b"])} for w in x.get("w", [])]} for x in ls]
                 for i, ls in d["pages"].items()}
        return int(d.get("dpi", DEFAULT_DPI)), pages
    except Exception:
        return None
