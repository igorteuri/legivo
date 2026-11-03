"""Análise de página: colunas (calhas), linhas, palavras e figuras.

Inspirado no K2pdfopt: procura calhas verticais em branco que persistem por uma
altura mínima, divide recursivamente em colunas e extrai as linhas de cada uma.
Opera só em NumPy; não depende de GUI.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import numpy.ma  # noqa: F401  (carrega já: o import preguiçoso do numpy, disputado por várias threads, travava a prévia)

from .params import Params


@dataclass
class Line:
    x0: int; y0: int; x1: int; y1: int
    baseline: int = 0
    words: list = field(default_factory=list)   # [(x0, x1)] em coordenadas da página
    cx0: int = 0; cx1: int = 0                  # extensão da coluna a que pertence
    kind: str = "text"                          # "text" | "fixed" (tabela/colunas não detectadas)
    ctx: int = 0

    @property
    def h(self): return self.y1 - self.y0
    @property
    def w(self): return self.x1 - self.x0


@dataclass
class Figure:
    x0: int; y0: int; x1: int; y1: int
    form: bool = False    # veio de um bloco de formulário/tabela
    table: bool = False   # tabela detectada por colunas alinhadas (vira <table> no EPUB)
    cover: list = field(default_factory=list)   # caixas de texto (px) sobre uma imagem: saem da figura ao compor


@dataclass
class Text:
    lines: list
    cx0: int
    cx1: int


@dataclass
class PageLayout:
    W: int
    H: int
    lh: int                                     # altura mediana de linha (px)
    elements: list = field(default_factory=list)

    def col_widths(self):
        return [(el.cx1 - el.cx0, len(el.lines)) for el in self.elements if isinstance(el, Text)]

    def overlay_rects(self):
        """Para o preview: (tipo, x0, y0, x1, y1)."""
        out = []
        for el in self.elements:
            if isinstance(el, Figure):
                out.append(("fig", el.x0, el.y0, el.x1, el.y1))
            else:
                y0 = min(l.y0 for l in el.lines); y1 = max(l.y1 for l in el.lines)
                out.append(("col", el.cx0, y0, el.cx1, y1))
                out += [("line" if l.kind == "text" else "fixed", l.x0, l.y0, l.x1, l.y1) for l in el.lines]
        return out


DEBUG = None   # lista opcional para diagnóstico das decisões de coluna


# ---------------------------------------------------------------- utilidades
def _runs(mask: np.ndarray, min_gap: int):
    """Intervalos [a,b) de True separados por >= min_gap posições vazias."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    cut = np.flatnonzero(np.diff(idx) > min_gap)
    starts = np.concatenate(([idx[0]], idx[cut + 1]))
    ends = np.concatenate((idx[cut], [idx[-1]])) + 1
    return list(zip(starts.tolist(), ends.tolist()))


def _true_runs(mask: np.ndarray):
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    cut = np.flatnonzero(np.diff(idx) > 1)
    starts = np.concatenate(([idx[0]], idx[cut + 1]))
    ends = np.concatenate((idx[cut], [idx[-1]])) + 1
    return list(zip(starts.tolist(), ends.tolist()))


def _gutter(empty, union, cg, central=0.5, one_side_ok=False):
    """Maior faixa vazia (>= cg) na parte central, com tinta dos dois lados. Com one_side_ok, basta tinta de
    um lado (primeiras linhas de uma coluna que começa mais alto que a vizinha)."""
    w = empty.size
    lo, hi = int(w * (0.5 - central / 2)), int(w * (0.5 + central / 2))
    best = None
    for a, b in _true_runs(empty[lo:hi]):
        a += lo; b += lo
        if b - a >= cg and (union[:a].any() or one_side_ok) and (union[b:].any() or one_side_ok) and union.any():
            if best is None or (b - a) > (best[1] - best[0]):
                best = (a, b)
    return best


def _strip_vertical_rules(ink: np.ndarray, min_frac: float = 0.2, max_w: int = 10):
    """Apaga (só da análise) filetes verticais finos e longos, como o separador entre colunas de
    provas e revistas. Eles impediam a detecção da calha em branco."""
    H, W = ink.shape
    cand = np.flatnonzero(ink.sum(axis=0) >= min_frac * H)
    if cand.size == 0 or cand.size > 0.1 * W:      # sem candidatos ou página escura: ignora
        return
    found = []
    for x in cand.tolist():
        col = ink[:, x].astype(np.int8)
        d = np.diff(np.concatenate(([0], col, [0])))
        st, en = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        k = int(np.argmax(en - st))
        if en[k] - st[k] >= min_frac * H:
            found.append((x, int(st[k]), int(en[k])))
    group: list = []
    for item in found + [None]:
        if item is not None and group and item[0] == group[-1][0] + 1:
            group.append(item); continue
        if group and len(group) <= max_w:
            for x, a, b in group:
                ink[a:b, x] = False
        group = [item] if item is not None else []


def _text_ink(gray: np.ndarray, boxes, p: Params) -> np.ndarray:
    """Tinta SÓ dentro das caixas de texto que o PDF informa. A forma das letras vem dos pixels, mas fundo
    texturizado, ilustrações e arte fora das caixas não contam. A cor do texto vem do PDF: texto escuro
    procura pixels mais escuros que o fundo da caixa; texto claro (sobre tarjas/arte escura), mais claros."""
    H, W = gray.shape
    delta = int(np.clip(255 - p.threshold, 30, 110))
    ink = np.zeros((H, W), bool)
    for b in boxes:
        dark = b[4] if len(b) > 4 else True
        x0, y0, x1, y1 = max(0, int(b[0]) - 1), max(0, int(b[1]) - 1), min(W, int(b[2]) + 2), min(H, int(b[3]) + 2)
        if x1 <= x0 or y1 <= y0:
            continue
        reg = gray[y0:y1, x0:x1].astype(np.int16)
        if dark:
            ink[y0:y1, x0:x1] = (int(np.percentile(reg, 90)) - reg) > delta
        else:
            ink[y0:y1, x0:x1] = (reg - int(np.percentile(reg, 10))) > delta
    return ink


def _marker_ink(gray: np.ndarray, boxes, p: Params) -> np.ndarray:
    """Marcas pequenas coladas ao texto que NÃO estão em caixas de texto do PDF: bolinhas das alternativas
    de prova, marcadores, caixas de seleção. Sem isto elas sumiam ao refluir (a tinta só contava dentro das
    caixas de texto). Só entram desenhos do tamanho de uma letra, na altura de uma linha e a até 2,5 alturas
    de uma palavra."""
    H, W = gray.shape
    out = np.zeros((H, W), bool)
    if not len(boxes):
        return out
    bm = np.zeros((H, W), bool)
    for b in boxes:
        bm[max(0, int(b[1]) - 1):min(H, int(b[3]) + 2), max(0, int(b[0]) - 1):min(W, int(b[2]) + 2)] = True
    dark = (gray < p.threshold) & ~bm
    rh = float(np.median([b[3] - b[1] for b in boxes]))
    order = sorted(boxes, key=lambda b: (b[1] + b[3]) / 2)
    bands: list = []                     # [y0, y1, [caixas]]
    for b in order:
        yc = (b[1] + b[3]) / 2
        if bands and yc <= bands[-1][1]:
            bands[-1][1] = max(bands[-1][1], b[3]); bands[-1][0] = min(bands[-1][0], b[1]); bands[-1][2].append(b)
        else:
            bands.append([b[1], b[3], [b]])
    found: list = []
    for y0, y1, bx in bands:
        y0, y1 = max(0, int(y0) - 1), min(H, int(y1) + 2)
        if y1 - y0 > 2.2 * rh:           # faixa alta demais: várias linhas coladas, não é uma linha de texto
            continue
        pad = int(0.3 * rh)                 # a bolinha pode passar um pouco da altura das letras
        y0, y1 = max(0, y0 - pad), min(H, y1 + pad)
        sub = dark[y0:y1]
        for a, c in _runs(sub.any(axis=0), 1):
            if not (0.6 * rh <= c - a <= 1.5 * rh):
                continue
            if sub[:, max(0, a - 3):a].any() or sub[:, c:c + 3].any():      # isolada: textura/ornamento não conta
                continue
            if dark[max(0, y0 - 4):y0, a:c].any() or dark[y1:y1 + 4, a:c].any():     # barras/halftone continuam acima ou abaixo
                continue
            rows = np.flatnonzero(sub[:, a:c].any(axis=1))
            if not (0.6 * rh <= rows[-1] - rows[0] + 1 <= 1.5 * rh):
                continue
            if any(b[0] - c <= 2.5 * rh and a - b[2] <= 2.5 * rh for b in bx):
                found.append((y0, y1, a, c))
    if len(found) < 3:        # uma marca solta é ornamento; marcadores de verdade se repetem na página
        return out
    for y0, y1, a, c in found:
        out[y0:y1, a:c] |= dark[y0:y1, a:c]
    return out


def _adaptive_ink(gray: np.ndarray, p: Params) -> np.ndarray:
    """Sem camada de texto: tinta = mais escuro que o fundo LOCAL. Só é usada quando o limiar fixo marca
    uma parte grande da página (fundo texturizado ou escuro); caso contrário vale o limiar fixo."""
    from PIL import Image, ImageFilter
    ink = gray < p.threshold
    if float(ink.mean()) < 0.18:
        return ink
    H, W = gray.shape
    small = Image.fromarray(gray).resize((max(8, W // 4), max(8, H // 4)), Image.BOX)
    bg = small.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9))
    bg = np.asarray(bg.resize((W, H), Image.BILINEAR)).astype(np.int16)
    return (bg - gray.astype(np.int16)) > int(np.clip(255 - p.threshold, 30, 110))


def _merge_rects(rects, pad: int = 0):
    """Une retângulos que se sobrepõem (ou que ficam a menos de `pad` px um do outro)."""
    rects = [list(r) for r in rects]
    changed = True
    while changed:
        changed = False
        out = []
        for r in rects:
            for o in out:
                if r[0] < o[2] + pad and o[0] < r[2] + pad and r[1] < o[3] + pad and o[1] < r[3] + pad:
                    o[0], o[1], o[2], o[3] = min(o[0], r[0]), min(o[1], r[1]), max(o[2], r[2]), max(o[3], r[3])
                    changed = True
                    break
            else:
                out.append(r)
        rects = out
    return [tuple(r) for r in rects]


def _find_tables(tdark: np.ndarray, p: Params, lh: int, gap_row: int, cg: int):
    """Procura tabelas: faixas de linhas consecutivas em que DOIS OU MAIS espaços verticais em branco
    se repetem alinhados (3+ colunas) e cada célula tem poucas palavras. Texto em colunas tem uma só
    calha e linhas cheias de palavras, por isso não é confundido com tabela.
    Devolve [(x0, y0, x1, y1)] em pixels."""
    H, W = tdark.shape
    rows = _runs(tdark.any(axis=1), gap_row)
    n = len(rows)
    gmin = max(int(0.55 * lh), int(0.5 * cg))
    wg = max(2, int(p.word_gap * lh))
    tables, i = [], 0
    while i < n - 2:
        union = np.zeros(W, bool)
        best = None
        base = None                                  # espaços (colunas) definidos pelas 3 primeiras linhas
        j = i
        while j < n:
            ra, rb = rows[j]
            if rb - ra > 2.2 * lh and j > i:        # linha muito alta: figura, não linha de tabela
                break
            rm = tdark[ra:rb].any(axis=0)
            if base is not None:
                # os espaços da tabela têm de continuar vazios; uma linha de texto corrido cobre vários deles
                covered = sum(1 for a, b in base if int(rm[a:b].sum()) > 2)
                if covered >= (1 if len(base) <= 2 else 2):
                    break
            un = union | rm
            xs = np.flatnonzero(un)
            if xs.size == 0:
                break
            off = int(xs[0])
            gaps = [(a + off, b + off) for a, b in _true_runs(~un[off:xs[-1] + 1]) if b - a >= gmin]
            if len(gaps) < 2:
                break
            union, best = un, (j, len(gaps))
            if j == i + 2:
                base = gaps
            j += 1
        if best is not None and best[0] - i + 1 >= 3:
            run = rows[i:best[0] + 1]
            words = [len(_runs(tdark[ra:rb].any(axis=0), wg)) for ra, rb in run]
            med = float(np.median(words))
            # tabela: células curtas (<= 3,2 palavras) e linhas curtas (<= 12 palavras). Texto justificado tem
            # 10 a 17 palavras por linha; espaços entre palavras alinhados por acaso não bastam.
            # Numa tabela de verdade quase toda linha tem conteúdo em VÁRIAS colunas. Dois blocos de texto lado a
            # lado (um parágrafo curto de um lado e uma lista longa do outro) deixam muitas linhas com um lado só.
            xs_u = np.flatnonzero(union)
            off_u = int(xs_u[0])
            gaps_u = [(a + off_u, b + off_u) for a, b in _true_runs(~union[off_u:xs_u[-1] + 1]) if b - a >= gmin]
            multi = 0
            if gaps_u:
                ga, gb = max(gaps_u, key=lambda g: g[1] - g[0])     # a maior calha: separa os dois lados
                mid = (ga + gb) // 2
                for ra, rb in run:
                    m_row = tdark[ra:rb].any(axis=0)
                    multi += bool(m_row[:mid].any() and m_row[mid:].any())
            multi_ok = multi >= 0.6 * len(run)
            # texto corrido numa das "células" = colunas de texto lado a lado, não tabela (ex.: prova com o
            # enunciado à esquerda e as alternativas "A ○ ..." à direita: os marcadores criam espaços alinhados)
            prose = _prose_cell_rows(tdark, run, gaps_u, wg) >= 0.5 * len(run)
            # a maior calha continua vazia acima/abaixo, com texto dos dois lados: é a calha entre as colunas da
            # página (alternativas lado a lado numa prova), não um espaço da tabela
            # espaços logo depois de colunas estreitas (marcadores "A", "○", "•") não separam células: se sobra
            # menos de 2 espaços "de verdade", são listas lado a lado (alternativas de prova), não tabela
            real_gaps = _real_gaps(tdark, run, union, gaps_u, lh)
            if multi_ok and not prose and real_gaps >= 2 and med <= 12 and med / (best[1] + 1) <= 3.2:
                xs = np.flatnonzero(union)
                x0t, x1t, top = int(xs[0]), int(xs[-1]) + 1, run[0][0]
                # cabeçalho de duas linhas ("Class of" / "Character"): sobe enquanto a linha de cima for
                # curta, estiver dentro da largura da tabela e colada nela
                k = i - 1
                while k >= 0 and top - rows[k][1] <= 1.3 * lh:
                    rx = np.flatnonzero(tdark[rows[k][0]:rows[k][1]].any(axis=0))
                    if rx.size == 0 or rx[0] < x0t - 2 or rx[-1] > x1t + 2 or len(_runs(tdark[rows[k][0]:rows[k][1]].any(axis=0), wg)) > 3:
                        break
                    top = rows[k][0]
                    k -= 1
                tables.append((x0t, top, x1t, run[-1][1]))
                i = best[0] + 1
                continue
        i += 1
    return tables


def _prose_cell_rows(tdark: np.ndarray, run, gaps, wg: int, min_words: int = 6) -> int:
    """Quantas linhas da faixa têm uma "célula" (trecho entre dois espaços da tabela) com texto corrido
    (>= min_words palavras). Células de tabela de verdade são curtas."""
    if not gaps:
        return 0
    W = tdark.shape[1]
    cuts = [0] + [(a + b) // 2 for a, b in gaps] + [W]
    n = 0
    for ra, rb in run:
        m = tdark[ra:rb].any(axis=0)
        if any(len(_runs(m[cuts[k]:cuts[k + 1]], wg)) >= min_words for k in range(len(cuts) - 1)):
            n += 1
    return n


def _real_gaps(tdark: np.ndarray, run, union: np.ndarray, gaps, lh: int) -> int:
    """Quantos espaços da tabela separam células de verdade: a coluna à esquerda é larga (> 1,3 linha) e as
    colunas dos dois lados têm conteúdo em boa parte das linhas. Espaços depois de uma coluna estreita
    (letra da alternativa, círculo, marcador) só separam o marcador do texto; uma coluna com conteúdo em
    poucas linhas (ex.: "Valor: 0,1 ponto(s)" de uma barra de questão) é coincidência de alinhamento."""
    xs = np.flatnonzero(union)
    if not gaps or xs.size == 0 or not run:
        return 0
    gs = sorted(gaps)
    edges = [int(xs[0])] + [v for g in gs for v in g] + [int(xs[-1]) + 1]
    cells = [(edges[2 * k], edges[2 * k + 1]) for k in range(len(gs) + 1)]
    occ = []
    for c0, c1 in cells:
        occ.append(sum(bool(tdark[ra:rb, c0:c1].any()) for ra, rb in run) / len(run))
    n = 0
    for k in range(len(gs)):
        (c0, c1) = cells[k]
        if c1 - c0 > 1.3 * lh and occ[k] >= 0.4 and occ[k + 1] >= 0.4:
            n += 1
    return n


def _word_spans(colmask: np.ndarray, line_h: int, fallback_gap: int):
    """Separa palavras. Procura o maior salto entre os espaços da linha (letras x palavras);
    evita colar palavras em títulos com letras espaçadas (versalete) ou fontes grandes."""
    glyphs = _runs(colmask, 1)
    if len(glyphs) >= 3:
        gaps = np.sort(np.array([glyphs[k + 1][0] - glyphs[k][1] for k in range(len(glyphs) - 1)], dtype=float))
        ratios = gaps[1:] / np.maximum(gaps[:-1], 1.0)
        k = int(np.argmax(ratios))
        if ratios[k] >= 1.8 and gaps[k + 1] >= 0.18 * line_h:
            return _runs(colmask, max(1, int((gaps[k] * gaps[k + 1]) ** 0.5)))
    return _runs(colmask, fallback_gap)


def _merge_table_pieces(elements: list, lh: int):
    """Uma tabela com linhas sombreadas vira vários pedaços. Une figuras vizinhas (coladas na vertical,
    com a mesma largura aproximada) quando pelo menos uma é tabela; texto/legenda no meio interrompe."""
    out: list = []
    for el in elements:
        if out and isinstance(el, Figure) and isinstance(out[-1], Figure) and (el.table or out[-1].table):
            a = out[-1]
            gap = el.y0 - a.y1
            ov = min(a.x1, el.x1) - max(a.x0, el.x0)
            if -lh <= gap <= 1.6 * lh and ov >= 0.5 * min(a.x1 - a.x0, el.x1 - el.x0):
                a.x0, a.y0, a.x1, a.y1 = min(a.x0, el.x0), min(a.y0, el.y0), max(a.x1, el.x1), max(a.y1, el.y1)
                a.table = a.form = True
                continue
        out.append(el)
    elements[:] = out


def _formlike_to_figures(elements: list, lh: int, skip=()):
    """Blocos em que muitas linhas têm grandes vãos (formulários, tabelas, cabeçalhos de prova)
    não devem ser reorganizados: viram uma figura única, mesmo que tenham sido divididos em colunas."""
    for k, el in enumerate(elements):
        if isinstance(el, Text) and len(el.lines) >= 3 and \
                sum(l.kind == "fixed" for l in el.lines) / len(el.lines) >= 0.4 and \
                not any(g[0] < max(l.x1 for l in el.lines) and min(l.x0 for l in el.lines) < g[2] and g[1] < max(l.y1 for l in el.lines)
                        and min(l.y0 for l in el.lines) < g[3] for g in skip):
            elements[k] = Figure(min(l.x0 for l in el.lines), min(l.y0 for l in el.lines),
                                 max(l.x1 for l in el.lines), max(l.y1 for l in el.lines), form=True)
    out: list = []
    for el in elements:
        if out and isinstance(el, Figure) and isinstance(out[-1], Figure):
            a = out[-1]
            oy = min(a.y1, el.y1) - max(a.y0, el.y0)
            gx = max(a.x0, el.x0) - min(a.x1, el.x1)
            if oy >= 0.5 * min(a.y1 - a.y0, el.y1 - el.y0) and gx <= 3 * lh:
                a.x0, a.y0, a.x1, a.y1 = min(a.x0, el.x0), min(a.y0, el.y0), max(a.x1, el.x1), max(a.y1, el.y1)
                a.form = a.form or el.form
                continue
        out.append(el)
    # a última linha do formulário (ex.: "Unid. ... Tur. ... Data") costuma ficar de fora: absorve
    changed = True
    while changed:
        changed = False
        for k, f in enumerate(out):
            if not (isinstance(f, Figure) and f.form):
                continue
            for j in (k - 1, k + 1):
                if j < 0 or j >= len(out) or not isinstance(out[j], Text) or len(out[j].lines) > 4:
                    continue
                t = out[j]
                ty0, ty1 = min(l.y0 for l in t.lines), max(l.y1 for l in t.lines)
                tx0, tx1 = min(l.x0 for l in t.lines), max(l.x1 for l in t.lines)
                gap = (ty0 - f.y1) if j > k else (f.y0 - ty1)
                ov = min(f.x1, tx1) - max(f.x0, tx0)
                if -lh <= gap <= 1.5 * lh and ov >= 0.6 * (tx1 - tx0) and any(l.kind == "fixed" for l in t.lines):
                    f.x0, f.y0, f.x1, f.y1 = min(f.x0, tx0), min(f.y0, ty0), max(f.x1, tx1), max(f.y1, ty1)
                    del out[j]
                    changed = True
                    break
            if changed:
                break
    elements[:] = out


def _absorb_labels(elements: list, lh: int):
    """Rótulos de diagramas (blocos de texto esparsos colados a uma figura) passam a fazer parte
    dela. Assim figura e rótulos são reduzidos juntos e mantêm a proporção do original.
    Parágrafos normais e legendas (linhas largas) não são absorvidos."""
    def sparse(t):
        if len(t.lines) < 2 or len(t.lines) > 8:
            return False
        w = max(l.x1 for l in t.lines) - min(l.x0 for l in t.lines)
        return w > 0 and float(np.median([l.w for l in t.lines])) / w < 0.75

    changed = True
    while changed:
        changed = False
        for i, f in enumerate(elements):
            if not isinstance(f, Figure):
                continue
            fw = max(1, f.x1 - f.x0)
            for j in (i - 1, i + 1):
                if j < 0 or j >= len(elements) or not isinstance(elements[j], Text):
                    continue
                t = elements[j]
                if not sparse(t):
                    continue
                tx0, tx1 = min(l.x0 for l in t.lines), max(l.x1 for l in t.lines)
                ty0, ty1 = min(l.y0 for l in t.lines), max(l.y1 for l in t.lines)
                gap = (ty0 - f.y1) if j > i else (f.y0 - ty1)
                if -lh <= gap <= 2.5 * lh and tx0 >= f.x0 - 0.15 * fw and tx1 <= f.x1 + 0.15 * fw:
                    f.x0, f.y0 = min(f.x0, tx0), min(f.y0, ty0)
                    f.x1, f.y1 = max(f.x1, tx1), max(f.y1, ty1)
                    del elements[j]
                    changed = True
                    break
            if changed:
                break


# ---------------------------------------------------------------- análise
def analyze(gray: np.ndarray, p: Params, fig_rects=(), exclude_rects=(), force_figs=(), vec=None,
            force_tables=(), force_text=()) -> PageLayout:
    H, W = gray.shape
    px_mm = p.render_dpi / 25.4
    # página de ilustração escura sem camada de texto (arte de página inteira, com o texto "desenhado" na imagem):
    # a análise por pixels só produziria fragmentos; a página inteira vira uma figura
    if (vec is None or len(vec.get("words", ())) < 8) and not exclude_rects and not force_figs and float(np.median(gray[::6, ::6])) < 140:
        return PageLayout(W, H, max(8, int(0.12 * p.render_dpi)), [Figure(0, 0, W, H)])
    image_figs: list = []
    wboxes = None
    if vec is not None and len(vec.get("words", ())) >= 8:
        # Modo texto: o PDF diz onde o texto está. Imagens raster viram figuras separadas (o texto que
        # passa por cima continua sendo texto); desenhos vetoriais só viram figura se tiverem pouco texto.
        wboxes = vec["words"]
        ink = _text_ink(gray, wboxes, p)
        ink |= _marker_ink(gray, wboxes, p)
        # riscos de textura dentro das margens das caixas formam "linhas" finas entre as linhas reais: remove
        _r = _runs(ink.any(axis=1), max(1, int(p.line_gap_mm * p.render_dpi / 25.4)))
        if len(_r) >= 6:
            _med = float(np.median([b - a for a, b in _r]))
            for a, b in _r:
                if b - a < 0.3 * _med:
                    ink[a:b] = False
        tarea = np.array([max(0, (b[2] - b[0])) * max(0, (b[3] - b[1])) for b in wboxes], float)
        wc = np.array([((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in wboxes])

        def cover_of(r):
            if not len(wc):
                return 0.0, []
            m = (wc[:, 0] >= r[0]) & (wc[:, 0] <= r[2]) & (wc[:, 1] >= r[1]) & (wc[:, 1] <= r[3])
            return float(tarea[m].sum()) / max(1.0, (r[2] - r[0]) * (r[3] - r[1])), [tuple(map(int, wboxes[k][:4])) for k in np.flatnonzero(m)]

        fig_rects = [tuple(int(v) for v in r) for r in vec.get("drawings", ()) if cover_of(r)[0] < 0.35]
        for r in fig_rects:      # traços do desenho (fora das caixas de texto) também são tinta dentro da figura
            x0_, y0_, x1_, y1_ = (max(0, int(r[0])), max(0, int(r[1])), min(W, int(r[2])), min(H, int(r[3])))
            dk = gray[y0_:y1_, x0_:x1_] < p.threshold
            if dk.size and float(dk.mean()) < 0.35:      # só desenhos esparsos (diagramas); áreas escuras sólidas não são tinta
                ink[y0_:y1_, x0_:x1_] |= dk
        for r in vec.get("images", ()):
            if cover_of(r)[0] < 0.5 and p.detect_figures:
                image_figs.append((tuple(int(v) for v in r), cover_of(r)[1]))
    else:
        ink = _adaptive_ink(gray, p)
    _strip_vertical_rules(ink)
    t, b = int(p.crop_top_mm * px_mm), int(p.crop_bottom_mm * px_mm)
    l, r = int(p.crop_left_mm * px_mm), int(p.crop_right_mm * px_mm)
    if t: ink[:t] = False
    if b: ink[H - b:] = False
    if l: ink[:, :l] = False
    if r: ink[:, W - r:] = False
    for ex0, ey0, ex1, ey1 in exclude_rects:
        ink[max(0, ey0):max(0, ey1), max(0, ex0):max(0, ex1)] = False

    rows0 = _runs(ink.any(axis=1), max(1, int(p.line_gap_mm * px_mm)))
    lh0 = max(8, int(np.median([bb - a for a, bb in rows0]))) if rows0 else int(0.12 * p.render_dpi)
    # modo texto: o PDF informa a altura real das linhas; as faixas de pixels de colunas vizinhas se fundem e inflam a mediana
    real_lh = None
    if wboxes is not None:
        _real = [b[3] - b[1] for b in wboxes if b[3] - b[1] > 4]
        if _real:
            real_lh = max(8, int(np.median(_real)))
            lh0 = min(lh0, real_lh)
    # figuras automaticas: descarta faixas baixas (titulos de secao, barras "Questao 1", fundos
    # cinza). Sao texto; trata-las como imagem quebrava a proporcao.
    figs = _merge_rects([(max(0, a), max(0, c), min(W, d), min(H, e)) for a, c, d, e in fig_rects], pad=int(0.7 * lh0)) \
        if p.detect_figures else []
    figs = [f for f in figs if (f[3] - f[1]) >= 2.5 * lh0 and (f[2] - f[0]) >= 2.5 * lh0]
    figs = [f for f in figs if (f[3] - f[1]) > 6 * lh0
            or len(_runs(ink[f[1]:f[3], f[0]:f[2]].any(axis=1), max(1, int(p.line_gap_mm * px_mm)))) > 2]
    forced = [(max(0, a), max(0, c), min(W, d), min(H, e)) for a, c, d, e in force_figs]
    figs = [f for f in figs if not any(f[0] < g[2] and g[0] < f[2] and f[1] < g[3] and g[1] < f[3] for g in forced)] + forced
    # blocos de formulário (caixas de campo): imagem única, com o espaço de escrever incluído
    forms = [(max(0, int(a)), max(0, int(b)), min(W, int(c)), min(H, int(d))) for a, b, c, d in (vec.get("forms", ()) if vec else ())]
    forms = [g for g in forms if not any(g[0] < q[2] and q[0] < g[2] and g[1] < q[3] and q[1] < g[3] for q in force_text)]
    figs = [f for f in figs if not any(f[0] < g[2] and g[0] < f[2] and f[1] < g[3] and g[1] < f[3] for g in forms)] + forms
    # respostas do usuário: "isto é texto" tira figuras/tabelas automáticas da região
    ntext = [(max(0, a), max(0, c), min(W, d), min(H, e)) for a, c, d, e in force_text]
    _hit = lambda r, g: r[0] < g[2] and g[0] < r[2] and r[1] < g[3] and g[1] < r[3]
    figs = [f for f in figs if f in forced or not any(_hit(f, g) for g in ntext)]
    gap_row = max(1, int(p.line_gap_mm * px_mm))
    cg = max(2, int(p.col_gap_mm * px_mm))
    ch = int(p.col_min_height_mm * px_mm)

    def fig_at(cx, cy):
        for f in figs:
            if f[0] <= cx <= f[2] and f[1] <= cy <= f[3]:
                return f
        return None

    # altura mediana de linha (ignora o que está dentro de figuras)
    hs = []
    for a, bb in _runs(ink.any(axis=1), gap_row):
        xs = np.flatnonzero(ink[a:bb].any(axis=0))
        if xs.size and fig_at((xs[0] + xs[-1]) // 2, (a + bb) // 2) is None:
            hs.append(bb - a)
    lh = int(np.median(hs)) if hs else int(0.12 * p.render_dpi)
    lh = max(8, lh)
    if real_lh:
        lh = min(lh, real_lh)

    # tabelas: máscara mais escura (as faixas cinza das linhas sombreadas não escondem os espaços).
    # A busca roda DENTRO de cada região (página, depois cada coluna), senão o texto de uma coluna
    # se funde com as linhas da tabela da outra.
    # limiar a partir do preto do próprio texto (2% mais escuro da página + folga): faixas cinza de linhas
    # sombreadas ficam de fora e não tapam os espaços entre as colunas
    t_thr = int(np.clip(float(np.percentile(gray[::3, ::3], 2)) + 45, 70, min(p.threshold, 140)))
    tdark = ink & (gray < t_thr)
    tset: set = set(forms)
    items: list = []
    ctx_counter = [0]

    def emit_line(x0, y0, x1, y1, ctx):
        if wboxes is not None and (y1 - y0) < 0.3 * lh:      # risco de textura entre linhas, não é texto
            return
        if y1 - y0 > 2.6 * lh:  # bloco muito alto sem retângulo de figura: trata como figura
            items.append(Figure(x0, y0, x1, y1))
        else:
            items.append(Line(x0, y0, x1, y1, ctx=ctx))

    def scan(x0, y0, x1, y1, depth):
        ctx_counter[0] += 1
        ctx = ctx_counter[0]
        sub = ink[y0:y1, x0:x1]
        if p.detect_figures:
            for tx0, ty0, tx1, ty1 in _find_tables(tdark[y0:y1, x0:x1], p, lh, gap_row, cg):
                t = (x0 + tx0, y0 + ty0, x0 + tx1, y0 + ty1)
                if t in tset or any(_hit(t, g) for g in forced) or any(_hit(t, g) for g in ntext):
                    continue
                figs[:] = [t] + [f for f in figs if not (f[0] < t[2] and t[0] < f[2] and f[1] < t[3] and t[1] < f[3])]
                tset.add(t)
        rows = _runs(sub.any(axis=1), gap_row)
        n, i = len(rows), 0
        can_cols = p.max_cols > 1 and depth < (1 if p.max_cols <= 2 else 2)
        while i < n:
            a, bb = rows[i]
            xs = np.flatnonzero(sub[a:bb].any(axis=0))
            rx0, rx1 = x0 + int(xs[0]), x0 + int(xs[-1]) + 1
            f = fig_at((rx0 + rx1) // 2, y0 + (a + bb) // 2)
            if f is not None:  # agrupa as linhas dentro do retângulo da figura
                j = i
                while j + 1 < n:
                    na, nb = rows[j + 1]
                    nxs = np.flatnonzero(sub[na:nb].any(axis=0))
                    if fig_at(x0 + (int(nxs[0]) + int(nxs[-1])) // 2, y0 + (na + nb) // 2) == f:
                        j += 1
                    else:
                        break
                seg = sub[rows[i][0]:rows[j][1]]
                fx = np.flatnonzero(seg.any(axis=0))
                items.append(Figure(x0 + int(fx[0]), y0 + rows[i][0], x0 + int(fx[-1]) + 1, y0 + rows[j][1],
                                    form=f in tset, table=f in tset))
                i = j + 1
                continue
            if can_cols:
                empty = np.ones(x1 - x0, bool)
                union = np.zeros(x1 - x0, bool)
                best = None
                j = i
                while j < n:
                    ja, jb = rows[j]
                    jx = np.flatnonzero(sub[ja:jb].any(axis=0))
                    if fig_at(x0 + (int(jx[0]) + int(jx[-1])) // 2, y0 + (ja + jb) // 2) is not None:
                        break
                    rm = sub[ja:jb].any(axis=0)
                    ne = empty & ~rm
                    un = union | rm
                    # as primeiras linhas podem ter texto de um lado só: uma coluna começa mais alto que a outra
                    g = _gutter(ne, un, cg, one_side_ok=j - i < 3)
                    if g is None:
                        break
                    empty, union, best = ne, un, (j, g)
                    j += 1
                valid = False
                if best is not None and rows[best[0]][1] - rows[i][0] >= ch:
                    j, (g0, g1) = best
                    run = rows[i:j + 1]
                    fl = float(np.mean([sub[ra:rb, :g0].any() for ra, rb in run]))
                    fr = float(np.mean([sub[ra:rb, g1:].any() for ra, rb in run]))
                    hs_run = [rb - ra for ra, rb in run if rb - ra <= 2.5 * lh]
                    rh = float(np.percentile(hs_run, 80)) if hs_run else float(lh)
                    rh = min(rh, 1.3 * lh)      # linhas de colunas vizinhas se sobrepõem e inflam as alturas; a calha real é bem maior
                    # coluna de verdade: texto dos dois lados na maior parte das linhas e calha mais
                    # larga que um espaço entre palavras de título (evita cortar títulos e cabeçalhos)
                    # linhas iniciais com texto de um lado só (coluna que começa mais alto) não contam para o
                    # tamanho mínimo: o trecho com as duas colunas tem de ser, sozinho, uma coluna de verdade
                    lead, seen_l, seen_r = 0, False, False
                    for ra, rb in run:
                        seen_l = seen_l or bool(sub[ra:rb, :g0].any())
                        seen_r = seen_r or bool(sub[ra:rb, g1:].any())
                        if seen_l and seen_r:
                            break
                        lead += 1
                    both = run[lead:]
                    valid = bool(both) and (len(both) >= 6 or both[-1][1] - both[0][0] >= 12 * lh) and fl >= 0.08 and fr >= 0.08 and (g1 - g0) >= 0.75 * rh
                    if DEBUG is not None:
                        DEBUG.append((depth, i, j, len(run), round(fl, 2), round(fr, 2), round(rh, 1), g1 - g0, rows[j][1] - rows[i][0], valid))
                if valid:
                    j, (g0, g1) = best
                    ya, yb = y0 + rows[i][0], y0 + rows[j][1]
                    scan(x0, ya, x0 + g0, yb, depth + 1)
                    scan(x0 + g1, ya, x1, yb, depth + 1)
                    i = j + 1
                    continue
            emit_line(rx0, y0 + a, rx1, y0 + bb, ctx)
            i += 1

    scan(0, 0, W, H, 0)

    # palavras, linha de base, extensão da coluna
    ctx_ext: dict[int, list] = {}
    for it in items:
        if isinstance(it, Line):
            e = ctx_ext.setdefault(it.ctx, [it.x0, it.x1])
            e[0], e[1] = min(e[0], it.x0), max(e[1], it.x1)
    for it in items:
        if not isinstance(it, Line):
            continue
        it.cx0, it.cx1 = ctx_ext[it.ctx]
        seg = ink[it.y0:it.y1, it.x0:it.x1]
        wg = max(2, int(p.word_gap * max(lh, it.h)))
        spans = _word_spans(seg.any(axis=0), it.h, wg)
        it.words = [(it.x0 + a, it.x0 + bb) for a, bb in spans]
        gaps = [spans[k + 1][0] - spans[k][1] for k in range(len(spans) - 1)]
        # marcador de item no inicio ("A" + circulo, bullet, "1."): o vao ate o texto nao torna a linha tabela
        m = 0
        while m < len(spans) - 1 and spans[m][1] - spans[m][0] <= 1.3 * lh and spans[m][1] - spans[0][0] <= 3 * lh:
            m += 1
        gaps = gaps[m:]
        if gaps and max(gaps) > 1.3 * max(lh, it.h):
            it.kind = "fixed"  # tabela ou colunas não separadas: não reorganizar
        prof = seg.sum(axis=1).astype(np.int64)
        hh = prof.size
        if hh > 4:
            lo = int(hh * 0.45)
            d = prof[:-1] - prof[1:]
            it.baseline = it.y0 + lo + int(np.argmax(d[lo:])) + 1
        else:
            it.baseline = it.y1

    # agrupa linhas consecutivas do mesmo contexto em elementos de texto
    elements: list = []
    for it in items:
        if isinstance(it, Figure):
            elements.append(it)
        elif (elements and isinstance(elements[-1], Text) and elements[-1].lines[-1].ctx == it.ctx
              and it.y0 - elements[-1].lines[-1].y1 <= 2.2 * lh):
            elements[-1].lines.append(it)
        else:
            elements.append(Text([it], it.cx0, it.cx1))
    # imagens raster do PDF: entram como figuras na ordem de leitura (por altura); o texto que está sobre
    # elas continua sendo texto e é apagado da figura ao compor (campo cover)
    def _ytop(e):
        return e.y0 if isinstance(e, Figure) else min(l.y0 for l in e.lines)
    for (ix0, iy0, ix1, iy1), cov in sorted(image_figs, key=lambda t: t[0][1]):
        ix0, iy0, ix1, iy1 = max(0, ix0), max(0, iy0), min(W, ix1), min(H, iy1)
        if ix1 - ix0 < 2.5 * lh0 or iy1 - iy0 < 2.5 * lh0:
            continue
        if any(isinstance(e, Figure) and e.x0 <= ix0 + 4 and e.y0 <= iy0 + 4 and e.x1 >= ix1 - 4 and e.y1 >= iy1 - 4 for e in elements):
            continue
        k = next((n for n, e in enumerate(elements) if _ytop(e) >= iy0 - lh), len(elements))
        elements.insert(k, Figure(ix0, iy0, ix1, iy1, cover=cov))
    for el in elements:        # linhas em região marcada como texto voltam a ser refeitas
        if isinstance(el, Text) and ntext:
            for l in el.lines:
                if any(_hit((l.x0, l.y0, l.x1, l.y1), g) for g in ntext):
                    l.kind = "text"
    for g in forms:            # formulário: uma figura só, do tamanho da caixa (inclui o espaço em branco dos campos)
        inside = [k for k, el in enumerate(elements) if isinstance(el, Figure)
                  and g[0] <= (el.x0 + el.x1) / 2 <= g[2] and g[1] <= (el.y0 + el.y1) / 2 <= g[3]]
        if inside:
            elements[inside[0]] = Figure(g[0], g[1], g[2], g[3], form=True, table=True)
            for k in reversed(inside[1:]):
                del elements[k]
    _merge_table_pieces(elements, lh)
    _formlike_to_figures(elements, lh, ntext)
    ftabs = [(max(0, a), max(0, c), min(W, d), min(H, e)) for a, c, d, e in force_tables]
    for el in elements:        # "isto é tabela"
        if isinstance(el, Figure) and any(_hit((el.x0, el.y0, el.x1, el.y1), g) for g in ftabs):
            el.table = el.form = True
    _absorb_labels(elements, lh)
    return PageLayout(W, H, lh, elements)
