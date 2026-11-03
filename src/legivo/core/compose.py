"""Composição: reorganiza (wrap) palavras e empilha em páginas do dispositivo."""
from __future__ import annotations
import numpy as np

from .imgops import resize as _rs, rotate_cw
from .layout import PageLayout, Figure, Text
from .params import Params


def _resize(img, s):
    return _rs(img, s)


def _greedy(ws, gap: int, width: int):
    """Quebra gulosa: lista de (palavras da linha, largura da linha)."""
    rows, row, rw = [], [], 0
    for w in ws:
        wi = w[0].shape[1]
        if row and rw + gap + wi > width:
            rows.append((row, rw)); row, rw = [], 0
        rw += (gap if row else 0) + wi
        row.append(w)
    if row:
        rows.append((row, rw))
    return rows


def _bg_level(img: np.ndarray) -> float:
    """Nível do fundo (percentil 90 da luminância)."""
    g = img if img.ndim == 2 else img.mean(axis=2)
    return float(np.percentile(g, 90))


def _clean_bg(img: np.ndarray) -> np.ndarray:
    """Clareia o fundo claro (cinza de pergaminho/papel) para branco, sem mexer em tarjas escuras."""
    g = img if img.ndim == 2 else img.mean(axis=2)
    bg = float(np.percentile(g, 90))
    if bg >= 248 or bg < 170:
        return img
    if img.ndim == 2:
        return np.minimum(255, img.astype(np.float32) * (255.0 / bg)).astype(np.uint8)
    chan = np.maximum(1.0, np.percentile(img.reshape(-1, 3), 90, axis=0))
    return np.minimum(255, img.astype(np.float32) * (255.0 / chan)).astype(np.uint8)


class Composer:
    def __init__(self, dev_w: int, dev_h: int, dev_dpi: int, p: Params, scale: float):
        self.W, self.H, self.p, self.s = dev_w, dev_h, p, scale
        self.color = bool(getattr(p, "color", False))
        self.m = max(2, round(p.margin_mm * dev_dpi / 25.4))
        self.avail, self.availh = dev_w - 2 * self.m, dev_h - 2 * self.m
        self.pages: list[np.ndarray] = []
        self.page_bg = 255.0
        self._new()

    # -- páginas de saída
    def _blank(self, h, w):
        return np.full((h, w, 3) if self.color else (h, w), 255, np.uint8)

    def _new(self):
        self.cur = self._blank(self.H, self.W)
        self.y, self.empty = self.m, True

    def flush(self):
        if not self.empty:
            self.pages.append(self.cur)
            self._new()

    def put(self, img, x, gap):
        h, w = img.shape[:2]
        if not self.empty and self.y + gap + h > self.H - self.m:
            self.flush()
        y = self.y + (0 if self.empty else gap)
        x = max(0, min(x, self.W - 1))
        h2, w2 = min(h, self.H - y), min(w, self.W - x)
        if h2 <= 0 or w2 <= 0:
            return
        self.cur[y:y + h2, x:x + w2] = img[:h2, :w2]
        self.y, self.empty = y + h2, False

    def finish(self):
        self.flush()
        out = []
        for pg in self.pages:
            if self.p.contrast != 1.0:
                pg = np.clip((pg.astype(np.float32) - 160) * self.p.contrast + 160, 0, 255).astype(np.uint8)
            if self.p.invert:
                pg = 255 - pg
            out.append(pg)
        return out

    # -- conteúdo
    def add_page(self, gray: np.ndarray, lay: PageLayout, ref_w: float = 0, rgb=None):
        if self.color and rgb is not None:
            gray = rgb
        elif self.color:
            gray = np.stack([gray] * 3, axis=2)
        # fundo da página: faixas bem mais escuras que ele (cabeçalho "Questão 1") são projeto, não sujeira
        g2 = gray[::4, ::4]
        self.page_bg = float(np.median(g2 if g2.ndim == 2 else g2.mean(axis=2)))
        for el in lay.elements:
            if isinstance(el, Figure):
                self._figure(gray, el, lay.lh)
            else:
                self._text(gray, el, lay.lh, ref_w, [e for e in lay.elements if isinstance(e, Figure)])
        if not self.p.continuous:
            self.flush()

    def _figure(self, gray, f, lh):
        crop = gray[f.y0:f.y1, f.x0:f.x1]
        if getattr(f, "cover", None):
            # texto sobre a imagem (ex.: parágrafos que passam por uma ilustração com fundo transparente)
            # já foi composto como texto: apaga-o da figura com a cor do fundo da página
            crop = crop.copy()
            bg = int(np.percentile(gray[::8, ::8], 85))
            for bx0, by0, bx1, by1 in f.cover:
                crop[max(0, by0 - f.y0 - 1):max(0, by1 - f.y0 + 2), max(0, bx0 - f.x0 - 1):max(0, bx1 - f.x0 + 2)] = bg
        h, w = crop.shape[:2]
        if h < 2 or w < 2:
            return
        # Proporção fiel: nada é ampliado além da escala do texto; só reduz para caber.
        s_fit = min(self.s, self.avail / w, self.availh / h)
        s = s_fit
        # Equilíbrio: figuras pequenas (com letras miúdas) são ampliadas um pouco, sem passar do
        # que cabe na tela.
        if self.p.small_fig_boost > 1 and w * self.s < 0.5 * self.avail:
            s = max(s, min(self.s * self.p.small_fig_boost, 0.6 * self.avail / w, self.availh / h))
            s_fit = s
        # Gira só figuras GRANDES e largas que ficariam pequenas demais (nunca faixas/títulos).
        if (self.p.rotate_figures and w > 1.25 * h and s_fit < 0.7 * self.s
                and h * s_fit >= 0.12 * self.avail):
            s_rot = min(self.s, self.avail / h, self.availh / w)
            if s_rot >= 1.5 * s_fit:
                crop, s = rotate_cw(crop), s_rot
        img = _resize(crop, s)
        self.put(img, self.m + max(0, (self.avail - img.shape[1]) // 2), round(self.p.para_gap * lh * self.s))

    def _paragraphs(self, el: Text, lh: int, ref_w: float = 0, figs=()):
        p, cw = self.p, max(1, el.cx1 - el.cx0)

        def near_fig(ln):
            # texto que contorna uma ilustração: a linha termina cedo (ou começa tarde) por causa da imagem
            return any(f.y0 < ln.y1 and f.y1 > ln.y0 and f.x0 < el.cx1 and f.x1 > el.cx0 for f in figs)
        # Largura de referência: colunas só com linhas curtas (alternativas de prova, listas) devem
        # ser comparadas com a coluna típica do documento, não com a própria largura.
        cw_eff = max(cw, int(0.9 * ref_w))
        right = el.cx0 + cw_eff
        pitches = [b.baseline - a.baseline for a, b in zip(el.lines, el.lines[1:])
                   if 0 < b.baseline - a.baseline < 3 * lh and a.ctx == b.ctx]
        pitch = float(np.median(pitches)) if pitches else 1.3 * lh
        paras, cur, prev, mode, big_prev, prev_li = [], [], None, "wrap", False, 0
        counts: dict = {}
        for l_ in el.lines:
            counts[round(l_.x0 / 8)] = counts.get(round(l_.x0 / 8), 0) + 1
        indents = {b for b, n in counts.items() if n >= 3 and abs(b * 8 - el.cx0) > 0.02 * cw}

        def flush():
            nonlocal cur
            if cur:
                paras.append((mode, cur))
            cur = []

        for idx, ln in enumerate(el.lines):
            nxt = el.lines[idx + 1] if idx + 1 < len(el.lines) else None
            if ln.kind == "fixed" or not p.wrap:
                flush(); paras.append(("fixed", [ln])); prev = None
                continue
            li, ri = ln.x0 - el.cx0, el.cx1 - ln.x1
            centered = li > 0.08 * cw and abs(li - ri) < 0.04 * cw
            # recuo que se repete na coluna = texto indentado (itens de lista), não centralização
            if centered and any(b in indents for b in (round(ln.x0 / 8) - 1, round(ln.x0 / 8), round(ln.x0 / 8) + 1)):
                centered = False
            big = ln.h > 1.5 * lh
            brk = prev is None
            join_center = False
            if prev is not None:
                # Título de várias linhas: letras grandes de tamanho parecido, com a última (ou alguma)
                # centralizada, são UMA frase só. Reorganiza como um bloco centralizado e balanceado.
                same_title = centered and big and big_prev and abs(ln.h - prev.h) < 0.25 * ln.h
                # Título de seção "pendurado": primeira linha cheia e a seguinte centralizada.
                hang = (centered and not big and mode != "center"
                        and (right - prev.x1) <= 0.12 * cw_eff and abs(ln.baseline - prev.baseline) <= 1.4 * pitch + 2)
                if same_title or hang:
                    join_center = True
                else:
                    wrapped = bool(figs) and (near_fig(prev) or near_fig(ln))
                    indent = li > 0.025 * cw and not wrapped
                    brk = (centered or mode == "center" or big != big_prev
                           or ((right - prev.x1) > p.para_short * cw_eff and (not wrapped or li - 0 > 0.05 * cw))
                           or ((prev_li - li) > 0.06 * cw and not wrapped)
                           or (ln.baseline - prev.baseline) > 1.4 * pitch + 2)
            if brk:
                flush()
                mode = "center" if centered else "wrap"
            if join_center:
                mode = "center"
            cur.append(ln); prev, big_prev, prev_li = ln, big, li
        flush()
        return paras

    def _word_img(self, wimg):
        """clean_bg clareia fundos acinzentados, mas uma faixa nitidamente mais escura que o fundo da página
        (barra de cabeçalho, linha sombreada) é desenho do documento e fica."""
        if not self.p.clean_bg:
            return wimg
        bg = _bg_level(wimg)
        if 170 <= bg < 248 and bg < self.page_bg - 14:
            return wimg
        return _clean_bg(wimg)

    def _text(self, gray, el: Text, lh: int, ref_w: float = 0, figs=()):
        p, s0 = self.p, self.s
        s = s0
        cw = max(1, el.cx1 - el.cx0)
        lead = round(p.leading * lh * s)
        pgap = round(p.para_gap * lh * s)
        for mode, lines in self._paragraphs(el, lh, ref_w, figs):
            # Equilíbrio de títulos: comprime o excesso de tamanho de linhas bem maiores que o corpo.
            rel = float(np.median([ln.h for ln in lines])) / max(1, lh)
            k = 1.0
            if p.title_balance < 1.0 and rel > 1.45 and mode in ("wrap", "center"):
                k = (1.45 + (rel - 1.45) * p.title_balance) / rel
            s = s0 * k
            if mode == "fixed":
                for k, ln in enumerate(lines):
                    img = gray[ln.y0:ln.y1, ln.x0:ln.x1]
                    img = _resize(self._word_img(img), min(s, self.avail / max(1, ln.w)))
                    self.put(img, self.m, pgap if k == 0 else lead)
                continue
            words, gaps = [], []
            for ln in lines:
                for k, (a, b) in enumerate(ln.words):
                    if k:
                        gaps.append(a - ln.words[k - 1][1])
                    wimg = gray[ln.y0:ln.y1, max(0, a - 1):b + 1]
                    words.append((self._word_img(wimg), ln.baseline - ln.y0))
            if not words:
                continue
            ref = max(lh, float(np.median([ln.h for ln in lines])))
            nominal = float(np.median(gaps)) if gaps else 0.28 * ref
            nominal = min(max(nominal, 0.18 * ref), 0.5 * ref)
            gpx = max(1, round(nominal * s))
            justify = False
            if p.justify and len(lines) > 2:
                flush_right = sum(1 for ln in lines[:-1] if el.cx1 - ln.x1 < 0.025 * cw)
                justify = flush_right >= 0.6 * (len(lines) - 1)
            ws = []
            for img, base in words:
                sc = min(s, self.avail / max(1, img.shape[1]))
                im = _resize(img, sc)
                ws.append((im, min(im.shape[0], max(1, round(base * sc)))))
            rows = _greedy(ws, gpx, self.avail)
            # Títulos e centralizados: quebra BALANCEADA (linhas de comprimento parecido, sem palavra
            # órfã). Procura a menor largura que ainda mantém o mesmo número de linhas.
            if (mode == "center" or rel > 1.45) and len(rows) > 1:
                lo, hi, n = max(w[0].shape[1] for w in ws), self.avail, len(rows)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if len(_greedy(ws, gpx, mid)) <= n:
                        hi = mid
                    else:
                        lo = mid + 1
                rows = _greedy(ws, gpx, hi)
            out_lines = [(row, rw, k == len(rows) - 1) for k, (row, rw) in enumerate(rows)]
            for k, (row, rw, last) in enumerate(out_lines):
                gap = float(gpx)
                if justify and not last and len(row) > 1:
                    extra = (self.avail - rw) / (len(row) - 1)
                    if extra < 2.5 * gpx:
                        gap = gpx + extra
                asc = max(b for _, b in row)
                desc = max(im.shape[0] - b for im, b in row)
                canvas = self._blank(asc + desc, self.avail)
                bgs = [_bg_level(im) for im, _ in row]
                if self.p.clean_bg and all(170 <= b < 248 and b < self.page_bg - 14 for b in bgs) and max(bgs) - min(bgs) < 12:
                    canvas[:] = int(round(min(bgs)))          # faixa de fundo contínua, inclusive entre as palavras
                x = (self.avail - rw) / 2 if mode == "center" else 0.0
                for im, b in row:
                    xi, yi = int(round(x)), asc - b
                    w_ = min(im.shape[1], self.avail - xi)
                    if w_ > 0:
                        reg = canvas[yi:yi + im.shape[0], xi:xi + w_]
                        canvas[yi:yi + im.shape[0], xi:xi + w_] = np.minimum(reg, im[:, :w_])
                    x += im.shape[1] + gap
                self.put(canvas, self.m, pgap if k == 0 else lead)
