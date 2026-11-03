"""Motor: abre o PDF, mantém caches por estágio e gera preview/conversão."""
from __future__ import annotations
import json, threading
from pathlib import Path
import numpy as np
import pymupdf

from .params import Params
from .layout import analyze, PageLayout
from .edits import Edit
from .compose import Composer
from .imgops import resize

DEVICES_FILE = Path(__file__).resolve().parent.parent / "profiles" / "devices.json"


def load_devices() -> list[dict]:
    return json.loads(DEVICES_FILE.read_text(encoding="utf-8"))["devices"]


def _form_blocks(drawings, words) -> list:
    """Blocos de formulário: várias caixas de contorno (campos "Nome", "Matrícula"...) empilhadas em linhas.
    Devolve os retângulos que as englobam, em pontos do PDF. O espaço em branco dos campos faz parte do
    formulário (é onde se escreve), então o bloco inteiro deve ficar como imagem, na ordem certa."""
    boxes = []
    for d in drawings:
        r = d["rect"]
        if d.get("fill") is None and d.get("color") is not None and r.width >= 40 and 10 <= r.height <= 45:
            boxes.append(pymupdf.Rect(r))
    n = len(boxes)
    if n < 4:
        return []
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a in range(n):
        for b in range(a + 1, n):
            ra, rb = boxes[a], boxes[b]
            gx = max(ra.x0, rb.x0) - min(ra.x1, rb.x1)
            gy = max(ra.y0, rb.y0) - min(ra.y1, rb.y1)
            if gx <= 12 and gy <= 0.6 * min(ra.height, rb.height) and (gx <= 0 or gy <= 0 or True):
                parent[find(a)] = find(b)
    groups: dict = {}
    for k in range(n):
        groups.setdefault(find(k), []).append(boxes[k])
    out = []
    for g in groups.values():
        rows = {round(r.y0 / 6) for r in g}
        if len(g) < 4 or len(rows) < 2:
            continue
        with_text = sum(any(r.x0 <= (w[0] + w[2]) / 2 <= r.x1 and r.y0 <= (w[1] + w[3]) / 2 <= r.y1 for w in words) for r in g)
        if with_text < 0.6 * len(g):
            continue
        u = pymupdf.Rect(g[0])
        for r in g[1:]:
            u |= r
        out.append(u)
    return out


class Engine:
    def __init__(self):
        self.doc = None
        self.path = ""
        self.n = 0
        self._lock = threading.Lock()
        self._clock = threading.Lock()           # protege os dicionários de cache (várias threads)
        self._vinfo: dict = {}
        self._gray: dict = {}
        self._rgb: dict = {}
        self._layout: dict = {}
        self._main_w: dict = {}
        self.edits: list[Edit] = []
        self._ev = 0
        self._font_info = None
        self.ocr_pages: dict[int, list] = {}     # página -> linhas reconhecidas pelo OCR
        self.ocr_dpi = 200
        self.ocr_enabled = False                 # usar o OCR nas páginas sem texto
        self._has_layer: dict[int, bool] = {}

    def open(self, path: str):
        with self._lock:
            self.doc = pymupdf.open(path)
            self.path, self.n = path, len(self.doc)
            self._gray.clear(); self._rgb.clear(); self._layout.clear(); self._main_w.clear()
            self.edits = []; self._ev += 1; self._font_info = None
            self.ocr_pages = {}; self.ocr_enabled = False; self._has_layer = {}

    # -- edições manuais
    def edits_for(self, i: int, kind: str | None = None) -> tuple:
        return tuple(e for e in self.edits if e.applies(i) and (kind is None or e.kind == kind))

    def add_edit(self, e: Edit):
        self.edits.append(e); self._ev += 1

    def replace_edit(self, k: int, e: Edit):
        if 0 <= k < len(self.edits):
            self.edits[k] = e; self._ev += 1

    def sample_text(self, i: int, x0: float, y0: float, x1: float, y1: float, limit: int = 60) -> str:
        """Texto do PDF dentro de um retângulo (frações da página), para descrever sugestões."""
        try:
            with self._lock:
                page = self.doc[i]
                r = page.rect
                clip = pymupdf.Rect(r.x0 + x0 * r.width, r.y0 + y0 * r.height, r.x0 + x1 * r.width, r.y0 + y1 * r.height)
                txt = " ".join(page.get_text("text", clip=clip).split())
            return txt[:limit]
        except Exception:
            return ""

    def remove_edit(self, k: int):
        if 0 <= k < len(self.edits):
            del self.edits[k]; self._ev += 1

    def clear_edits(self):
        self.edits = []; self._ev += 1

    def save_edits(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps([e.to_dict() for e in self.edits], ensure_ascii=False, indent=1), encoding="utf-8")

    def load_edits(self, path):
        try:
            self.edits = [Edit.from_dict(d) for d in json.loads(Path(path).read_text(encoding="utf-8"))]
        except Exception:
            self.edits = []
        self._ev += 1

    def _put(self, cache: dict, key, val, limit: int):
        """Guarda no cache com limite de tamanho; seguro entre threads (prévia, miniaturas, mapa)."""
        with self._clock:
            if key not in cache and len(cache) > limit:
                cache.pop(next(iter(cache)), None)
            cache[key] = val

    def _vector_info(self, i: int):
        """(imagens, desenhos agrupados) da página em pontos do PDF. UMA leitura de get_drawings por página
        (antes eram duas, e o cluster_drawings lia de novo). Chamar com self._lock já tomado."""
        hit = self._vinfo.get(i)
        if hit is not None:
            return hit
        page = self.doc[i]
        imgs, draws, forms = [], [], []
        try:
            imgs = [pymupdf.Rect(d["bbox"]) for d in page.get_image_info()]
            dr = page.get_drawings()
            if len(dr) < 4000:
                draws = [pymupdf.Rect(r) for r in page.cluster_drawings(drawings=dr)]
                forms = _form_blocks(dr, page.get_text("words"))
        except Exception:
            pass
        self._put(self._vinfo, i, (imgs, draws, forms), 40)
        return imgs, draws, forms

    # -- estágio 1: renderização + retângulos de figuras
    def page_data(self, i: int, p: Params):
        key = (i, p.render_dpi, p.detect_figures)
        hit = self._gray.get(key)
        if hit is not None:
            return hit
        with self._lock:
            page = self.doc[i]
            pix = page.get_pixmap(dpi=p.render_dpi, colorspace=pymupdf.csGRAY)
            gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy()
            rects = []
            if p.detect_figures:
                sc, area = p.render_dpi / 72, page.rect.get_area()
                imgs_, draws_, _f = self._vector_info(i)
                found = imgs_ + draws_
                for r in found:
                    r = pymupdf.Rect(r) & page.rect
                    if r.is_empty or not (0.01 < r.get_area() / area < 0.6) or r.width < 20 or r.height < 20:
                        continue
                    rects.append((int(r.x0 * sc), int(r.y0 * sc), int(r.x1 * sc), int(r.y1 * sc)))
        self._put(self._gray, key, (gray, rects), 6)
        return gray, rects

    def page_rgb(self, i: int, p: Params):
        """Página renderizada em cores (só quando a opção de cor está ligada)."""
        key = (i, p.render_dpi)
        if key not in self._rgb:
            with self._lock:
                pix = self.doc[i].get_pixmap(dpi=p.render_dpi, colorspace=pymupdf.csRGB)
                arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3).copy()
            self._put(self._rgb, key, arr, 3)
        return self._rgb[key]

    def page_vec(self, i: int, p: Params):
        """Palavras (caixas), imagens raster e desenhos vetoriais da página, em pixels do render. None se não há texto."""
        sc = p.render_dpi / 72.0
        if self.ocr_enabled and not self.page_has_text(i):
            words = [tuple(v * sc for v in w[:4]) + (True,) for w in self.ocr_words(i)]
            return {"words": words, "images": [], "drawings": []} if words else None
        with self._lock:
            page = self.doc[i]
            raw = page.get_text("words")
            if len(raw) < 8:
                return None
            # trechos de texto (spans) com a cor do texto: define se a tinta é mais escura ou mais clara que o fundo
            words = []
            for blk in page.get_text("dict")["blocks"]:
                for ln in blk.get("lines", []):
                    for sp in ln["spans"]:
                        if not sp["text"].strip():
                            continue
                        c = sp.get("color", 0)
                        lum = 0.299 * ((c >> 16) & 255) + 0.587 * ((c >> 8) & 255) + 0.114 * (c & 255)
                        x0, y0, x1, y1 = sp["bbox"]
                        words.append((x0 * sc, y0 * sc, x1 * sc, y1 * sc, lum < 140))
            area, imgs, draws, forms = page.rect.get_area(), [], [], []
            imgs_, draws_, forms_ = self._vector_info(i)
            forms = [tuple(v * sc for v in (r.x0, r.y0, r.x1, r.y1)) for r in forms_]
            for src, dst in ((imgs_, imgs), (draws_, draws)):
                for r in src:
                    r = r & page.rect
                    if not r.is_empty and 0.01 < r.get_area() / area < 0.6 and r.width >= 20 and r.height >= 20:
                        dst.append(tuple(v * sc for v in (r.x0, r.y0, r.x1, r.y1)))
        return {"words": words, "images": imgs, "drawings": draws, "forms": forms}

    # -- estágio 2: layout (cache)
    def layout(self, i: int, p: Params) -> PageLayout:
        ed = self.edits_for(i)
        key = (i,) + p.layout_key() + (ed, i in self.ocr_pages)
        lay = self._layout.get(key)
        if lay is None:
            gray, rects = self.page_data(i, p)
            h, w = gray.shape
            lay = analyze(gray, p, rects,
                          [e.px(w, h) for e in ed if e.kind == "exclude"],
                          [e.px(w, h) for e in ed if e.kind in ("figure", "table")],
                          vec=self.page_vec(i, p),
                          force_tables=[e.px(w, h) for e in ed if e.kind == "table"],
                          force_text=[e.px(w, h) for e in ed if e.kind == "text"])
            self._put(self._layout, key, lay, 400)
        return lay

    def main_col_width(self, p: Params) -> float:
        key = p.layout_key() + (self._ev,)
        if key in self._main_w:
            return self._main_w[key]
        step = max(1, self.n // 8)
        ws = []
        for i in range(0, self.n, step):
            for w, nl in self.layout(i, p).col_widths():
                ws += [w] * nl
        v = float(np.median(ws)) if ws else 1000.0
        self._put(self._main_w, key, v, 50)
        return v

    def scale(self, p: Params, dev: dict) -> float:
        m = max(2, round(p.margin_mm * dev["dpi"] / 25.4))
        return (dev["width"] - 2 * m) / self.main_col_width(p) * p.size

    # -- estágio 3: composição
    def compose_pages(self, pages: list[int], p: Params, dev: dict) -> list[np.ndarray]:
        c = Composer(dev["width"], dev["height"], dev["dpi"], p, self.scale(p, dev))
        ref = self.main_col_width(p)
        for i in pages:
            c.add_page(self.page_data(i, p)[0], self.layout(i, p), ref, self.page_rgb(i, p) if p.color else None)
        return c.finish()

    def preview(self, i: int, p: Params, dev: dict, max_h: int = 1400, fmt: str = "pdf", fontsize: float = 12.0):
        """Devolve (página original reduzida em cinza, regiões detectadas em frações da página,
        páginas de saída em cinza). O desenho das regiões é feito pela interface."""
        gray, _ = self.page_data(i, p)
        lay = self.layout(i, p)
        H, W = gray.shape
        k = min(1.0, max_h / H)
        small = resize(gray, size=(max(1, round(W * k)), max(1, round(H * k)))) if k < 1 else gray
        items = [(kind, x0 / W, y0 / H, x1 / W, y1 / H) for kind, x0, y0, x1, y1 in lay.overlay_rects()]
        q = Params.from_dict({**p.to_dict(), "continuous": False})
        outs = self.epub_preview(i, p, dev, fontsize) if fmt == "epub" else self.compose_pages([i], q, dev)
        fi = self.font_info(p)
        if fmt == "epub":
            info = {"body_pt": float(fontsize), "size": p.size, "rel": None}
        else:
            s = self.scale(p, dev)
            info = {"body_pt": fi["body_pt"] * s * p.render_dpi / dev["dpi"], "size": p.size,
                    "rel": fi["title_pt"] / fi["body_pt"]}
        return small, items, outs, info

    # -- OCR
    def page_has_text(self, i: int) -> bool:
        """A página tem camada de texto no PDF (não é só imagem)?"""
        if i not in self._has_layer:
            with self._lock:
                self._has_layer[i] = len(self.doc[i].get_text("words")) >= 8
        return self._has_layer[i]

    def scanned_pages(self) -> list[int]:
        return [i for i in range(self.n) if not self.page_has_text(i)]

    def ocr_page(self, i: int):
        """Reconhece (e guarda em memória) o texto da página i. Devolve as linhas."""
        if i in self.ocr_pages:
            return self.ocr_pages[i]
        from . import ocr
        with self._lock:
            pix = self.doc[i].get_pixmap(dpi=self.ocr_dpi, colorspace=pymupdf.csRGB)
            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3).copy()
        self.ocr_pages[i] = ocr.recognize(img)
        return self.ocr_pages[i]

    def ocr_words(self, i: int) -> list[tuple]:
        """Palavras reconhecidas pelo OCR, em pontos: [(x0, y0, x1, y1, texto)]. Sem posição de palavra, usa a linha."""
        k = 72.0 / self.ocr_dpi
        out = []
        for l in self.ocr_page(i):
            ws = l.get("words") or [{"t": l["text"], "b": l["box"]}]
            out += [(w["b"][0] * k, w["b"][1] * k, w["b"][2] * k, w["b"][3] * k, w["t"]) for w in ws]
        return out

    def ocr_spans(self, i: int) -> list[dict]:
        from . import ocr
        return ocr.to_spans(self.ocr_page(i), self.ocr_dpi)

    def run_ocr(self, pages=None, progress=None, cancel=None, cache_path=None) -> int:
        """Roda o OCR nas páginas sem texto (ou nas indicadas). Devolve quantas páginas foram reconhecidas."""
        from . import ocr
        todo = [i for i in (pages if pages is not None else self.scanned_pages()) if i not in self.ocr_pages]
        for k, i in enumerate(todo):
            if cancel and cancel():
                break
            self.ocr_page(i)
            if progress:
                progress(k + 1, len(todo))
            if cache_path and (k + 1) % 5 == 0:
                ocr.save_cache(cache_path, self.ocr_dpi, self.ocr_pages)
        if cache_path and self.ocr_pages:
            ocr.save_cache(cache_path, self.ocr_dpi, self.ocr_pages)
        self.ocr_enabled = True
        return len(todo)

    def load_ocr(self, cache_path) -> bool:
        from . import ocr
        res = ocr.load_cache(cache_path)
        if not res:
            return False
        self.ocr_dpi, self.ocr_pages = res
        self.ocr_enabled = bool(self.ocr_pages)
        return self.ocr_enabled

    # -- tamanho de fonte (equivalência em pontos, como no Word)
    def font_info(self, p: Params) -> dict:
        """Tamanho de fonte do corpo e do maior título do original, em pontos."""
        if self._font_info is not None:
            return self._font_info
        body, title = None, None
        try:
            from .epub import _page_spans, _body_size
            spans = [s for i in range(min(self.n, 3)) for s in _page_spans(self, i)]
            if spans:
                body = _body_size(self, list(range(self.n)), p)
                big = [s["size"] for s in spans if len(s["text"].strip()) >= 12 and s["size"] > body * 1.15]
                title = max(big) if big else body * 1.5
        except Exception:
            pass
        if body is None:                       # PDF só de imagem: estima pela altura das linhas
            body = max(6.0, self.layout(0, p).lh * 72.0 / p.render_dpi) if self.n else 10.0
            title = body * 1.5
        self._font_info = {"body_pt": float(body), "title_pt": float(title)}
        return self._font_info

    def overlay_composite(self, pages, width: int = 700, progress=None, cancel=None):
        """Empilha as páginas (cinza) com transparência: o que se repete na mesma posição fica escuro e nítido."""
        from .imgops import resize as _rs
        acc, size = None, None
        for k, i in enumerate(pages):
            if cancel and cancel():
                return None
            g = self.render_thumb(i, width)
            if size is None:
                size = (g.shape[1], g.shape[0])
            elif (g.shape[1], g.shape[0]) != size:
                g = _rs(g, size=size)
            d = (255.0 - g.astype(np.float32)) / 255.0
            acc = d if acc is None else acc + d
            if progress:
                progress(k + 1, len(pages))
        if acc is None:
            return None
        mean = acc / len(pages)
        # realça o que é frequente (cabeçalhos/rodapés ficam escuros; o corpo do texto vira mancha clara)
        out = 255.0 * (1.0 - np.clip(mean * 2.4, 0.0, 1.0) ** 0.8)
        return out.astype(np.uint8)

    # -- miniaturas e mapa de páginas
    def render_thumb(self, i: int, width: int = 120) -> np.ndarray:
        with self._lock:
            page = self.doc[i]
            sc = width / page.rect.width
            pix = page.get_pixmap(matrix=pymupdf.Matrix(sc, sc), colorspace=pymupdf.csGRAY)
            return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy()

    def page_map(self, p: Params, dev: dict, cancel=None, progress=None):
        """Para cada página de origem: (primeira, última) página de saída em que ela aparece (fluxo contínuo)."""
        c = Composer(dev["width"], dev["height"], dev["dpi"], p, self.scale(p, dev))
        ref = self.main_col_width(p)
        out = []
        for i in range(self.n):
            if cancel and cancel():
                return None
            start = len(c.pages) + 1
            c.add_page(self.page_data(i, p)[0], self.layout(i, p), ref)
            end = len(c.pages) + (0 if c.empty else 1)
            out.append((start, max(start, end)))
            if progress:
                progress(i + 1, self.n)
        return out, len(c.finish())

    def epub_preview(self, i: int, p: Params, dev: dict, fontsize: float = 12.0, max_pages: int = 8):
        """Mostra como a página ficaria num EPUB, com o tamanho de tela do dispositivo."""
        from .epub import build_epub
        data = build_epub(self, p, [i])
        d = pymupdf.open(stream=data, filetype="epub")
        d.layout(rect=pymupdf.Rect(0, 0, dev["width"] * 72 / dev["dpi"], dev["height"] * 72 / dev["dpi"]), fontsize=fontsize)
        outs = []
        for k in range(min(d.page_count, max_pages)):
            pix = d[k].get_pixmap(dpi=dev["dpi"], colorspace=pymupdf.csGRAY)
            outs.append(np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy())
        return outs

    # -- conversão completa
    def convert(self, dst: str, p: Params, dev: dict, pages=None, progress=None, cancel=None) -> int:
        pages = list(pages) if pages is not None else list(range(self.n))
        c = Composer(dev["width"], dev["height"], dev["dpi"], p, self.scale(p, dev))
        ref = self.main_col_width(p)
        for k, i in enumerate(pages):
            if cancel and cancel():
                return 0
            c.add_page(self.page_data(i, p)[0], self.layout(i, p), ref, self.page_rgb(i, p) if p.color else None)
            if progress:
                progress(k + 1, len(pages))
        out = pymupdf.open()
        for img in c.finish():
            pg = out.new_page(width=dev["width"] * 72 / dev["dpi"], height=dev["height"] * 72 / dev["dpi"])
            if img.ndim == 3:        # colorido: JPEG para o arquivo não ficar enorme
                import io
                from PIL import Image
                buf = io.BytesIO(); Image.fromarray(img).save(buf, "JPEG", quality=88, optimize=True)
                pg.insert_image(pg.rect, stream=buf.getvalue())
            else:
                pg.insert_image(pg.rect, pixmap=pymupdf.Pixmap(pymupdf.csGRAY, dev["width"], dev["height"], img.tobytes(), False))
        out.save(dst, deflate=True)
        return len(out)
