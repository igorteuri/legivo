"""Exportação para EPUB: reorganiza o TEXTO do PDF (sem transformar em imagens).

Usa a mesma análise de página do conversor de PDF (colunas, ordem de leitura, parágrafos,
títulos, figuras, edições do usuário) e a camada de texto do PDF para gerar um EPUB
reflowable. O aparelho decide o tamanho da letra. Figuras, tabelas e formulários entram
como imagens recortadas do PDF.
"""
from __future__ import annotations
import datetime, html, io, re, uuid, zipfile
from collections import Counter
from dataclasses import replace

import numpy as np
from PIL import Image

from .compose import Composer
from .layout import Figure, Text
from .params import Params

END_PUNCT = tuple(".!?:;…”\"')]»")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


# ------------------------------------------------------------------ texto do PDF
def _page_spans(engine, i: int):
    if engine.ocr_enabled and not engine.page_has_text(i):
        return engine.ocr_spans(i)                    # página de imagem: usa o texto reconhecido pelo OCR
    with engine._lock:
        d = engine.doc[i].get_text("dict")
    out = []
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            for s in l["spans"]:
                if s["text"].strip():
                    out.append(s)
    return out


def _fmt(span):
    f, name = span.get("flags", 0), span.get("font", "").lower()
    return (bool(f & 16) or "bold" in name or "black" in name,
            bool(f & 2) or "italic" in name or "oblique" in name,
            bool(f & 1))


def _line_runs(spans):
    """Spans de uma linha, da esquerda para a direita -> [(texto, negrito, itálico, sobrescrito)]."""
    runs, prev = [], None
    for s in sorted(spans, key=lambda s: s["bbox"][0]):
        t = _CTRL.sub("", s["text"])
        if prev is not None:
            gap = s["bbox"][0] - prev["bbox"][2]
            if gap > 0.12 * max(prev["size"], 1) and not runs[-1][0].endswith(" ") and not t.startswith(" "):
                runs.append((" ", False, False, False))
        b, i, sup = _fmt(s)
        runs.append((t, b, i, sup))
        prev = s
    return runs


def _join_lines(lines_runs, vocab=frozenset()):
    """Junta as linhas de um parágrafo; reúne palavras hifenizadas na quebra de linha.
    Se a palavra composta (com hífen) aparece em outro ponto do documento, o hífen é mantido."""
    out: list = []
    for runs in lines_runs:
        if not runs:
            continue
        if out:
            last = out[-1][0]
            first = runs[0][0].lstrip()
            if last.endswith(("-", "­")) and len(last) > 2 and last[-2].isalpha() and first[:1].islower():
                a = re.findall(r"[^\W\d_]+$", last[:-1])
                b = re.match(r"[^\W\d_]+", first)
                if a and b and f"{a[0]}-{b.group(0)}".lower() in vocab:
                    out.append(("", False, False, False))        # hífen verdadeiro: mantém, sem espaço
                else:
                    out[-1] = (last[:-1],) + out[-1][1:]
            else:
                out.append((" ", False, False, False))
        out.extend(runs)
    return out


def _plain(runs) -> str:
    return re.sub(r"\s+", " ", "".join(r[0] for r in runs)).strip()


def _runs_html(runs) -> str:
    merged: list = []
    for t, b, i, s in runs:
        if merged and merged[-1][1:] == (b, i, s):
            merged[-1] = (merged[-1][0] + t, b, i, s)
        else:
            merged.append((t, b, i, s))
    parts = []
    for t, b, i, s in merged:
        t = html.escape(re.sub(r"\s+", " ", t), quote=False)
        if not t.strip():
            parts.append(t)
            continue
        if b:
            t = f"<b>{t}</b>"
        if i:
            t = f"<i>{t}</i>"
        if s:
            t = f"<sup>{t}</sup>"
        parts.append(t)
    return "".join(parts).strip()


def _guess_lang(text: str) -> str:
    w = re.findall(r"[a-záéíóúâêôãõç]+", text.lower())[:3000]
    en = sum(x in ("the", "and", "of", "to", "in", "is", "that", "with") for x in w)
    pt = sum(x in ("de", "que", "e", "o", "a", "do", "da", "em", "para", "com", "não") for x in w)
    return "en" if en > pt else "pt-BR"


# ------------------------------------------------------------------ tabelas
def _page_words(engine, i: int):
    """Palavras da página: [(x0, y0, x1, y1, texto)] em pontos. Páginas de imagem usam as linhas do OCR."""
    if engine.ocr_enabled and not engine.page_has_text(i):
        return engine.ocr_words(i)
    with engine._lock:
        return [(w[0], w[1], w[2], w[3], w[4]) for w in engine.doc[i].get_text("words")]


def _table_rows(words, box_pt):
    """Monta linhas e colunas a partir das palavras dentro da caixa. Devolve lista de listas de células, ou None."""
    bx0, by0, bx1, by1 = box_pt
    ws = [w for w in words if bx0 <= (w[0] + w[2]) / 2 <= bx1 and by0 <= (w[1] + w[3]) / 2 <= by1 and str(w[4]).strip()]
    if len(ws) < 6:
        return None
    hs = sorted(w[3] - w[1] for w in ws)
    mh = max(2.0, hs[len(hs) // 2])
    # linhas: agrupa por centro vertical
    ws.sort(key=lambda w: (w[1] + w[3]) / 2)
    rows, cur, cy = [], [], None
    for w in ws:
        c = (w[1] + w[3]) / 2
        if cur and abs(c - cy) > 0.55 * mh:
            rows.append(cur); cur = []
        cur.append(w)
        cy = sum((x[1] + x[3]) / 2 for x in cur) / len(cur)
    if cur:
        rows.append(cur)
    if len(rows) < 2:
        return None
    # colunas: um espaço vertical vale como separador se estiver livre na grande maioria das linhas
    # (títulos largos e linhas de texto corrido não derrubam a detecção)
    x_lo, x_hi = min(w[0] for w in ws), max(w[2] for w in ws)
    res = 2.0
    n = max(2, int((x_hi - x_lo) / res) + 1)
    cover = np.zeros(n, int)
    for r in rows:
        m = np.zeros(n, bool)
        for w in r:
            m[int((w[0] - x_lo) / res):int((w[2] - x_lo) / res) + 1] = True
        cover += m
    free = cover <= max(0, int(0.12 * len(rows)))
    gaps, k = [], 0
    while k < n:
        if free[k]:
            j = k
            while j < n and free[j]:
                j += 1
            if (j - k) * res >= 0.9 * mh and k > 0 and j < n:
                gaps.append(x_lo + (k + j) / 2 * res)
            k = j
        else:
            k += 1
    if not gaps:
        return None
    cuts = [-1e9] + gaps + [1e9]
    table = []
    for r in rows:
        r.sort(key=lambda w: w[0])
        cells = [[] for _ in range(len(cuts) - 1)]
        for w in r:
            xc = (w[0] + w[2]) / 2
            for c in range(len(cuts) - 1):
                if cuts[c] <= xc < cuts[c + 1]:
                    cells[c].append(str(w[4])); break
        table.append([" ".join(c) for c in cells])
    keep = [c for c in range(len(cuts) - 1) if any(row[c] for row in table)]
    table = [[row[c] for c in keep] for row in table]
    # linhas de título (uma só célula preenchida, no começo): saem da tabela
    title = []
    while table and sum(1 for c in table[0] if c) <= 1 and len(table) > 3:
        title.append(" ".join(c for c in table.pop(0) if c))
    full = sum(1 for row in table if sum(1 for c in row if c) >= 2)
    if len(keep) < 2 or len(table) < 2 or full < max(2, int(0.5 * len(table))):
        return None
    return title, table


def _table_html(table) -> str:
    out = ['<table>']
    for r, row in enumerate(table):
        tag = "th" if r == 0 and len(table) >= 4 and all(not re.fullmatch(r"[\d.,%+()*\-–/ ]+", c) for c in row if c) else "td"
        out.append("<tr>" + "".join(f"<{tag}>{html.escape(re.sub(chr(32) + '+', chr(32), c))}</{tag}>" for c in row) + "</tr>")
    out.append("</table>")
    return "".join(out)


# ------------------------------------------------------------------ imagens
def _image_bytes(engine, i: int, box, p: Params, max_w: int = 1100):
    """Recorta a região (px do render de análise) do PDF em cores. Devolve (bytes, extensão, tipo MIME)."""
    x0, y0, x1, y1 = box
    sc = 72.0 / p.render_dpi
    pad = 2
    with engine._lock:
        import pymupdf
        page = engine.doc[i]
        clip = pymupdf.Rect((x0 - pad) * sc, (y0 - pad) * sc, (x1 + pad) * sc, (y1 + pad) * sc) & page.rect
        pix = page.get_pixmap(clip=clip, dpi=170, colorspace=pymupdf.csRGB)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if im.width > max_w:
        im = im.resize((max_w, max(1, round(im.height * max_w / im.width))), Image.LANCZOS)
    buf = io.BytesIO()
    if im.getcolors(maxcolors=4096) is not None and len(im.getcolors(maxcolors=4096)) <= 256:
        im.convert("P", palette=Image.ADAPTIVE, colors=64).save(buf, "PNG", optimize=True)
        return buf.getvalue(), "png", "image/png"
    im.save(buf, "JPEG", quality=84, optimize=True)
    return buf.getvalue(), "jpg", "image/jpeg"


# ------------------------------------------------------------------ construção do conteúdo
class _Doc:
    def __init__(self):
        self.blocks: list[dict] = []
        self.images: list[tuple[str, bytes, str]] = []
        self.page_first_block: dict[int, int] = {}

    def add_image(self, data, ext, mime) -> str:
        name = f"img{len(self.images) + 1:04d}.{ext}"
        self.images.append((name, data, mime))
        return name


def _hyphen_vocab(engine, pages) -> frozenset:
    """Palavras compostas com hífen que aparecem no meio de uma linha (hífen verdadeiro)."""
    words = set()
    for i in pages:
        for s in _page_spans(engine, i):
            t = s["text"]
            for m in re.finditer(r"([^\W\d_]{2,})-([^\W\d_]{2,})", t):
                words.add(f"{m.group(1)}-{m.group(2)}".lower())
    return frozenset(words)


def _body_size(engine, pages, p) -> float:
    c: Counter = Counter()
    for i in pages[:: max(1, len(pages) // 8)]:
        for s in _page_spans(engine, i):
            c[round(s["size"], 1)] += len(s["text"])
    return c.most_common(1)[0][0] if c else 10.0


def _collect(engine, p: Params, pages, progress=None, cancel=None) -> _Doc:
    q = replace(p, wrap=True, continuous=True)            # o EPUB sempre reorganiza
    vocab = _hyphen_vocab(engine, pages)
    doc = _Doc()
    comp = Composer(658, 1024, 212, q, 1.0)
    ref_w = engine.main_col_width(q)
    body = _body_size(engine, pages, q)
    sc = 72.0 / q.render_dpi
    for n, i in enumerate(pages):
        if cancel and cancel():
            return doc
        lay = engine.layout(i, q)
        spans = _page_spans(engine, i)
        lines = [(l, el) for el in lay.elements if isinstance(el, Text) for l in el.lines]
        by_line: dict[int, list] = {}
        for s in spans:
            cx, cy = (s["bbox"][0] + s["bbox"][2]) / 2 / sc, (s["bbox"][1] + s["bbox"][3]) / 2 / sc
            best, best_area = None, None
            for l, _ in lines:
                if l.x0 - 6 <= cx <= l.x1 + 6 and l.y0 - 4 <= cy <= l.y1 + 4:
                    a = l.w * l.h
                    if best is None or a < best_area:
                        best, best_area = l, a
            if best is None:        # sem linha que contenha o centro: usa a de maior sobreposição (OCR é menos preciso)
                bx0, by0, bx1, by1 = (v / sc for v in s["bbox"])
                sa = max(1.0, (bx1 - bx0) * (by1 - by0)); top = 0.0
                for l, _ in lines:
                    ov = max(0.0, min(bx1, l.x1) - max(bx0, l.x0)) * max(0.0, min(by1, l.y1) - max(by0, l.y0))
                    if ov / sa > max(0.3, top):
                        best, top = l, ov / sa
            if best is not None:
                by_line.setdefault(id(best), []).append(s)
        first = True

        def push(block):
            nonlocal first
            block["page"] = i
            if first:
                doc.page_first_block[i] = len(doc.blocks)
                first = False
            doc.blocks.append(block)

        for el in lay.elements:
            if isinstance(el, Figure):
                tb = None
                if el.table or el.form:
                    tb = _table_rows(_page_words(engine, i), tuple(v * sc for v in (el.x0, el.y0, el.x1, el.y1)))
                if tb:
                    for t in tb[0]:
                        push({"kind": "p", "level": 0, "runs": [(t, True, False, False)], "text": t, "center": False})
                    push({"kind": "table", "html": _table_html(tb[1]), "text": " ".join(c for r in tb[1] for c in r)})
                else:
                    data, ext, mime = _image_bytes(engine, i, (el.x0, el.y0, el.x1, el.y1), q)
                    push({"kind": "img", "name": doc.add_image(data, ext, mime)})
                continue
            paras = comp._paragraphs(el, lay.lh, ref_w, [e for e in lay.elements if isinstance(e, Figure)])
            k = 0
            while k < len(paras):
                mode, ls = paras[k]
                if mode == "fixed":                      # tabelas/formulários: imagem do trecho
                    grp = list(ls)
                    while k + 1 < len(paras) and paras[k + 1][0] == "fixed":
                        k += 1
                        grp += paras[k][1]
                    box = (min(l.x0 for l in grp), min(l.y0 for l in grp), max(l.x1 for l in grp), max(l.y1 for l in grp))
                    tb = _table_rows(_page_words(engine, i), tuple(v * sc for v in box)) if len(grp) >= 2 else None
                    if tb:
                        for t in tb[0]:
                            push({"kind": "p", "level": 0, "runs": [(t, True, False, False)], "text": t, "center": False})
                        push({"kind": "table", "html": _table_html(tb[1]), "text": " ".join(c for r in tb[1] for c in r)})
                    else:
                        data, ext, mime = _image_bytes(engine, i, box, q)
                        push({"kind": "img", "name": doc.add_image(data, ext, mime)})
                    k += 1
                    continue
                lr = [_line_runs(by_line.get(id(l), [])) for l in ls]
                runs = _join_lines(lr, vocab)
                text = _plain(runs)
                k += 1
                if not text:
                    continue
                sizes = [s["size"] for l in ls for s in by_line.get(id(l), [])]
                size = sorted(sizes)[len(sizes) // 2] if sizes else body
                all_bold = all(r[1] for r in runs if r[0].strip())
                ratio = size / body if body else 1.0
                level = 0
                if ratio >= 1.7:
                    level = 1
                elif ratio >= 1.35:
                    level = 2
                elif ratio >= 1.18 or (all_bold and len(text) <= 160 and len(ls) <= 3 and not text.endswith(".")):
                    level = 3
                push({"kind": "h" if level else "p", "level": level, "runs": runs, "text": text,
                      "center": mode == "center"})
        # Linhas do OCR que não casaram com nenhuma linha detectada (letra muito clara, p.ex.) não podem se
        # perder: entram como parágrafos no fim da página, exceto as que caem em figuras ou áreas excluídas.
        if engine.ocr_enabled and not engine.page_has_text(i):
            assigned = {id(sp) for v in by_line.values() for sp in v}
            figs = [el for el in lay.elements if isinstance(el, Figure)]
            excl = [e.px(lay.W, lay.H) for e in engine.edits_for(i, "exclude")]

            def hidden(sp):
                cx, cy = (sp["bbox"][0] + sp["bbox"][2]) / 2 / sc, (sp["bbox"][1] + sp["bbox"][3]) / 2 / sc
                return (any(f.x0 <= cx <= f.x1 and f.y0 <= cy <= f.y1 for f in figs)
                        or any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in excl))
            orph = sorted((sp for sp in spans if id(sp) not in assigned and not hidden(sp)),
                          key=lambda sp: (round(sp["bbox"][1] / max(1.0, sp["size"] * 0.6)), sp["bbox"][0]))
            groups: list[list] = []
            for sp in orph:
                if groups and sp["bbox"][1] - groups[-1][-1]["bbox"][3] < 0.9 * sp["size"] and abs(sp["size"] - groups[-1][-1]["size"]) < 0.25 * sp["size"]:
                    groups[-1].append(sp)
                else:
                    groups.append([sp])
            for g in groups:
                runs = _join_lines([_line_runs([sp]) for sp in g], vocab)
                text = _plain(runs)
                if not text:
                    continue
                size = sorted(sp["size"] for sp in g)[len(g) // 2]
                ratio = size / body if body else 1.0
                level = 1 if ratio >= 1.7 else 2 if ratio >= 1.35 else 3 if ratio >= 1.18 else 0
                push({"kind": "h" if level else "p", "level": level, "runs": runs, "text": text, "center": False})
        if progress:
            progress(n + 1, len(pages))
    # une parágrafos cortados por quebra de coluna ou de página
    merged: list[dict] = []
    for b in doc.blocks:
        if (merged and b["kind"] == "p" and merged[-1]["kind"] == "p" and not merged[-1]["center"] and not b["center"]
                and not merged[-1]["text"].endswith(END_PUNCT) and b["text"][:1].islower()):
            merged[-1]["runs"] = _join_lines([merged[-1]["runs"], b["runs"]], vocab)
            merged[-1]["text"] = _plain(merged[-1]["runs"])
            continue
        merged.append(b)
    # reindexa o primeiro bloco de cada página
    firsts, seen = {}, set()
    for idx, b in enumerate(merged):
        if b["page"] not in seen:
            seen.add(b["page"]); firsts[b["page"]] = idx
    doc.blocks, doc.page_first_block = merged, firsts
    return doc


# ------------------------------------------------------------------ empacotamento
CSS = """body { margin: 0 4%; line-height: 1.35; }
p { margin: 0 0 0.7em 0; text-align: left; }
h1, h2, h3 { line-height: 1.2; margin: 1.1em 0 0.5em 0; page-break-after: avoid; }
h1 { font-size: 1.6em; } h2 { font-size: 1.3em; } h3 { font-size: 1.1em; }
.center { text-align: center; }
img { max-width: 100%; height: auto; display: block; margin: 0.8em auto; }
sup { font-size: 0.75em; }
table { border-collapse: collapse; margin: 0.8em auto; font-size: 0.9em; max-width: 100%; }
td, th { border: 1px solid #888; padding: 0.15em 0.4em; vertical-align: top; }
th { font-weight: bold; text-align: left; }
"""


def _xhtml(title: str, body: str, lang: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" xml:lang="{lang}">\n'
            f'<head><meta charset="utf-8"/><title>{html.escape(title)}</title>'
            '<link rel="stylesheet" type="text/css" href="../style.css"/></head>\n'
            f"<body>\n{body}\n</body></html>\n")


def build_epub(engine, p: Params, pages=None, title: str | None = None, progress=None, cancel=None) -> bytes:
    """Gera o EPUB em memória. `pages`: índices (base 0); None = documento inteiro."""
    pages = list(pages) if pages is not None else list(range(engine.n))
    doc = _collect(engine, p, pages, progress, cancel)
    meta = engine.doc.metadata or {}
    title = title or (meta.get("title") or "").strip() or "Documento"
    author = (meta.get("author") or "").strip()
    sample = " ".join(b["text"] for b in doc.blocks[:60] if b["kind"] == "p")
    lang = _guess_lang(sample)

    # ids de âncora (páginas) e de títulos
    html_blocks: list[str] = []
    page_anchor: dict[int, str] = {}
    headings: list[tuple[int, str, str]] = []              # (nível, texto, id)
    for idx, b in enumerate(doc.blocks):
        attrs = ""
        if doc.page_first_block.get(b["page"]) == idx:
            page_anchor[b["page"]] = f"pg{b['page'] + 1}"
            attrs = f' id="pg{b["page"] + 1}"'
        if b["kind"] == "img":
            html_blocks.append(f'<div{attrs}><img src="../images/{b["name"]}" alt=""/></div>')
        elif b["kind"] == "table":
            html_blocks.append(f'<div{attrs}>{b["html"]}</div>')
        elif b["kind"] == "h":
            if not attrs:
                attrs = f' id="h{idx}"'
            hid = re.search(r'id="([^"]+)"', attrs).group(1)
            headings.append((b["level"], b["text"], hid))
            cls = ' class="center"' if b["center"] else ""
            html_blocks.append(f'<h{b["level"]}{attrs}{cls}>{_runs_html(b["runs"])}</h{b["level"]}>')
        else:
            cls = ' class="center"' if b["center"] else ""
            html_blocks.append(f'<p{attrs}{cls}>{_runs_html(b["runs"])}</p>')

    # capítulos: a cada 12 páginas de origem (arquivos menores abrem mais rápido nos leitores)
    chunk_of_block, chunks, cur, cur_pages = [], [], [], set()
    for idx, b in enumerate(doc.blocks):
        if cur and len(cur_pages | {b["page"]}) > 12:
            chunks.append(cur); cur, cur_pages = [], set()
        cur.append(idx); cur_pages.add(b["page"])
        chunk_of_block.append(len(chunks))
    if cur:
        chunks.append(cur)
    if not chunks:
        chunks = [[]]
    files = []
    for k, idxs in enumerate(chunks):
        body = "\n".join(html_blocks[j] for j in idxs) or "<p></p>"
        files.append((f"text/c{k + 1:03d}.xhtml", _xhtml(title, body, lang)))
    file_of_id: dict[str, str] = {}
    for idx, b in enumerate(doc.blocks):
        fn = files[chunk_of_block[idx]][0]
        for m in re.finditer(r'id="([^"]+)"', html_blocks[idx][:80]):
            file_of_id[m.group(1)] = fn

    # índice: sumário do PDF (se existir) ou os títulos detectados
    toc: list[tuple[int, str, str]] = []                    # (nível, texto, href)
    pdf_toc = engine.doc.get_toc() or []
    anchored = sorted(page_anchor)
    if pdf_toc:
        for lvl, text, pg in pdf_toc:
            if pg - 1 not in pages and pg - 1 < pages[0]:
                pg = pages[0] + 1
            target = next((a for a in anchored if a >= pg - 1), None)
            if target is None:
                continue
            aid = page_anchor[target]
            toc.append((max(1, lvl), text.strip() or "—", f"{file_of_id.get(aid, files[0][0])}#{aid}"))
    if not toc:
        for lvl, text, hid in headings:
            toc.append((min(lvl, 2), text[:120], f"{file_of_id.get(hid, files[0][0])}#{hid}"))
    if not toc:
        toc.append((1, title, files[0][0]))

    def nav_html():
        root: list = []
        stack = [(0, root)]
        for lvl, text, href in toc:
            lvl = max(1, lvl)
            while stack[-1][0] >= lvl:
                stack.pop()
            node = (text, href, [])
            stack[-1][1].append(node)
            stack.append((lvl, node[2]))

        def render(nodes):
            return "<ol>" + "".join(
                f'<li><a href="{html.escape(h)}">{html.escape(t)}</a>{render(ch) if ch else ""}</li>' for t, h, ch in nodes) + "</ol>"
        return render(root)

    nav = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
           f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}">'
           f'<head><meta charset="utf-8"/><title>{html.escape(title)}</title></head><body>'
           f'<nav epub:type="toc" id="toc"><h1>Sumário</h1>\n{nav_html()}\n</nav></body></html>\n')
    uid = f"urn:uuid:{uuid.uuid4()}"
    ncx_points = "".join(
        f'<navPoint id="n{k}" playOrder="{k}"><navLabel><text>{html.escape(t)}</text></navLabel><content src="{html.escape(h)}"/></navPoint>'
        for k, (l, t, h) in enumerate(toc, 1))
    ncx = ('<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           f'<head><meta name="dtb:uid" content="{uid}"/></head><docTitle><text>{html.escape(title)}</text></docTitle>'
           f'<navMap>{ncx_points}</navMap></ncx>')

    cover_name = None
    if pages:
        try:
            import pymupdf
            with engine._lock:
                pix = engine.doc[pages[0]].get_pixmap(dpi=90, colorspace=pymupdf.csRGB)
                cim = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            cb = io.BytesIO(); cim.save(cb, "JPEG", quality=85)
            cover_name = "cover.jpg"; cover_bytes = cb.getvalue()
        except Exception:
            cover_name = None
    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
                '<item id="css" href="style.css" media-type="text/css"/>']
    spine = []
    for k, (fn, _) in enumerate(files, 1):
        manifest.append(f'<item id="c{k}" href="{fn}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{k}"/>')
    for k, (name, _, mime) in enumerate(doc.images, 1):
        manifest.append(f'<item id="i{k}" href="images/{name}" media-type="{mime}"/>')
    if cover_name:
        manifest.append(f'<item id="cover" href="images/{cover_name}" media-type="image/jpeg" properties="cover-image"/>')
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    opf = ('<?xml version="1.0" encoding="utf-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:identifier id="uid">{uid}</dc:identifier><dc:title>{html.escape(title)}</dc:title><dc:language>{lang}</dc:language>'
           + (f"<dc:creator>{html.escape(author)}</dc:creator>" if author else "")
           + f'<meta property="dcterms:modified">{now}</meta>'
           + ('<meta name="cover" content="cover"/>' if cover_name else "")
           + f'</metadata><manifest>{"".join(manifest)}</manifest><spine toc="ncx">{"".join(spine)}</spine></package>')
    container = ('<?xml version="1.0" encoding="utf-8"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/toc.ncx", ncx, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", CSS, zipfile.ZIP_DEFLATED)
        for fn, content in files:
            z.writestr("OEBPS/" + fn, content, zipfile.ZIP_DEFLATED)
        for name, data, _ in doc.images:
            z.writestr("OEBPS/images/" + name, data, zipfile.ZIP_STORED)
        if cover_name:
            z.writestr("OEBPS/images/" + cover_name, cover_bytes, zipfile.ZIP_STORED)
    return buf.getvalue()


def export_epub(engine, dst: str, p: Params, pages=None, progress=None, cancel=None) -> int:
    """Salva o EPUB em `dst`. Devolve a quantidade de páginas de origem processadas (0 se cancelado)."""
    pages_l = list(pages) if pages is not None else list(range(engine.n))
    data = build_epub(engine, p, pages_l, progress=progress, cancel=cancel)
    if cancel and cancel():
        return 0
    with open(dst, "wb") as f:
        f.write(data)
    return len(pages_l)


def has_text(engine, sample: int = 6) -> bool:
    """O PDF tem camada de texto? (amostra de páginas espalhadas). Com OCR concluído, conta como texto."""
    if engine.ocr_enabled and engine.ocr_pages:
        return True
    n = engine.n
    idx = sorted({round(k * (n - 1) / max(1, sample - 1)) for k in range(sample)}) if n else []
    total = 0
    for i in idx:
        with engine._lock:
            total += len(engine.doc[i].get_text("words"))
    return total >= 30 * max(1, len(idx)) / 3
