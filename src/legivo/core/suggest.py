"""Sugestão automática de cabeçalhos, rodapés e números de página repetidos."""
from __future__ import annotations
from dataclasses import dataclass

from .edits import Edit
from .layout import Text
from .params import Params


@dataclass
class Suggestion:
    edit: Edit
    where: str        # "topo" | "rodapé"
    sample: str       # texto de exemplo (se o PDF tiver texto)
    pages: int        # em quantas páginas amostradas se repete
    sample_page: int = 0   # página (base 0) em que o exemplo aparece


def _spread(idx: list[int], k: int) -> list[int]:
    if len(idx) <= k:
        return idx
    return [idx[round(j * (len(idx) - 1) / (k - 1))] for j in range(k)]


def _union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _candidates(engine, i: int, p: Params, band: float):
    """Elementos da faixa do topo/rodapé da página i: (faixa, balde de altura, lado, retângulo)."""
    lay = engine.layout(i, p)
    lines = [l for el in lay.elements if isinstance(el, Text) for l in el.lines]
    H, W = lay.H, lay.W
    thin = lambda l: l.h < 0.4 * lay.lh          # filetes (linhas finas) não contam como texto vizinho
    body = [l for l in lines if not thin(l)]
    out = []
    for l in lines:
        yc = (l.y0 + l.y1) / 2 / H
        if yc < band:
            kind = "topo"
        elif yc > 1 - band:
            kind = "rodapé"
        else:
            continue
        rect = (l.x0 / W, l.y0 / H, l.x1 / W, l.y1 / H)
        if thin(l):
            if l.w >= 0.4 * W:                   # filete largo: faz parte do cabeçalho/rodapé
                out.append((kind, int(yc * 50), 1, rect))
            continue
        if kind == "topo":
            below = [m.y0 for m in body if m.y0 >= l.y1]
            isolated = not below or (min(below) - l.y1) >= 1.5 * lay.lh
        else:
            above = [m.y1 for m in body if m.y1 <= l.y0]
            isolated = not above or (l.y0 - max(above)) >= 1.5 * lay.lh
        if not isolated:
            continue
        xc = (l.x0 + l.x1) / 2 / W
        out.append((kind, int(yc * 50), 0 if xc < 1 / 3 else (1 if xc < 2 / 3 else 2), rect))
    return out


def _find_clusters(engine, p, pages, band, need, tick):
    """Elementos que se repetem na mesma posição em pelo menos `need` das páginas dadas."""
    clusters: dict[tuple, dict] = {}
    for i in pages:
        for kind, yb, side, rect in _candidates(engine, i, p, band):
            c = clusters.setdefault((kind, yb, side), {"kind": kind, "pages": set(), "rect": list(rect), "first": i})
            c["pages"].add(i)
            c["rect"] = _union(c["rect"], rect)
        tick()
    found = [c for c in clusters.values() if len(c["pages"]) >= need]
    # une o que está vizinho na vertical (texto do cabeçalho + filete embaixo dele)
    out: list[dict] = []
    for c in sorted(found, key=lambda c: (c["kind"], c["rect"][1])):
        for o in out:
            if o["kind"] == c["kind"] and c["rect"][1] - o["rect"][3] <= 0.035 and o["rect"][1] - c["rect"][3] <= 0.035:
                o["rect"] = _union(o["rect"], c["rect"])
                o["pages"] |= c["pages"]
                break
        else:
            out.append({"kind": c["kind"], "pages": set(c["pages"]), "rect": list(c["rect"]), "first": c["first"]})
    return out


def suggest_margins(engine, p: Params, band: float = 0.14, per_group: int = 12, progress=None):
    """Procura cabeçalhos, rodapés e números de página repetidos."""
    n = engine.n
    if n < 2:
        return []
    if n <= 8:   # documento curto: não separa ímpares e pares
        groups = {"all": list(range(n))}
    else:
        groups = {"odd": _spread(list(range(0, n, 2)), per_group), "even": _spread(list(range(1, n, 2)), per_group)}
    total, done = sum(len(v) for v in groups.values()), [0]

    def tick():
        done[0] += 1
        if progress:
            progress(done[0], total)

    found = {}
    for par, pages in groups.items():
        need = max(2, -(-len(pages) * 3 // 5)) if par == "all" else max(3, int(0.5 * len(pages) + 0.5))
        found[par] = _find_clusters(engine, p, pages, band, need, tick)

    pad = 0.004

    def mk(c, scope, extra_pages=0):
        x0, y0, x1, y1 = c["rect"]
        r = (max(0.0, x0 - pad), max(0.0, y0 - pad), min(1.0, x1 + pad), min(1.0, y1 + pad))
        return Suggestion(Edit("exclude", *r, scope=scope, page=-1), c["kind"],
                          engine.sample_text(c["first"], *r), len(c["pages"]) + extra_pages, c["first"])

    result: list[Suggestion] = []
    if "all" in found:
        result = [mk(c, "all") for c in found["all"]]
    else:
        used = set()
        for c in found["odd"]:
            m = next((j for j, c2 in enumerate(found["even"])
                      if c2["kind"] == c["kind"] and abs(c2["rect"][1] - c["rect"][1]) <= 0.035), None)
            if m is not None:
                used.add(m)
                merged = {**c, "rect": _union(c["rect"], found["even"][m]["rect"])}
                result.append(mk(merged, "all", len(found["even"][m]["pages"])))
            else:
                result.append(mk(c, "odd"))
        result += [mk(c, "even") for j, c in enumerate(found["even"]) if j not in used]
    result.sort(key=lambda s: (s.where != "topo", s.edit.y0))
    return result
