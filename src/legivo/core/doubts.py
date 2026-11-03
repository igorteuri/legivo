"""Dúvidas do reconhecimento: pontos em que o programa não tem certeza e pergunta ao usuário.

Sem modelo de linguagem: só regras de confiança sobre o próprio layout. Cada dúvida vira uma pergunta simples;
a resposta é gravada como uma edição (Edit) e vale para o documento, como as exclusões.
"""
from __future__ import annotations
from dataclasses import dataclass

from .edits import Edit
from .layout import Figure, Text


@dataclass
class Doubt:
    page: int                  # base 0
    kind: str                  # "tabela" | "figura_com_texto"
    rect: tuple                # fração da página (x0, y0, x1, y1)
    pergunta: str
    score: float               # quanto maior, mais duvidoso (ordena a fila)
    opcoes: tuple              # (rótulo do botão, kind da Edit ou None para "manter")
    tag: str = ""              # tipo fino da dúvida (para achar as parecidas)


def _frac(el, lay):
    return (el.x0 / lay.W, el.y0 / lay.H, el.x1 / lay.W, el.y1 / lay.H)


def find_doubts_page(engine, i: int, p, min_score: float = 0.35) -> list[Doubt]:
    from .epub import _page_words, _table_rows
    lay = engine.layout(i, p)
    out: list[Doubt] = []
    vec = engine.page_vec(i, p)
    words_px = vec["words"] if vec else []
    sc = 72.0 / p.render_dpi
    for el in lay.elements:
        if not isinstance(el, Figure):
            continue
        w, h = el.x1 - el.x0, el.y1 - el.y0
        if w >= 0.9 * lay.W and h >= 0.9 * lay.H:
            continue                                           # página de arte inteira: sem dúvida
        inside = [b for b in words_px if el.x0 <= (b[0] + b[2]) / 2 <= el.x1 and el.y0 <= (b[1] + b[3]) / 2 <= el.y1]
        if el.table or el.form:
            tb = _table_rows(_page_words(engine, i), tuple(v * sc for v in (el.x0, el.y0, el.x1, el.y1)))
            if tb is None:
                score, why, tag = 0.9, "Parece uma tabela, mas não consegui montar as colunas.", "sem_colunas"
            else:
                rows, cols = len(tb[1]), max(len(r) for r in tb[1])
                score = 0.2 + (0.35 if rows <= 3 else 0.0) + (0.3 if cols <= 2 else 0.0)
                why = f"Detectei uma tabela de {rows} linhas por {cols} colunas."
                tag = f"t{min(rows, 4)}x{min(cols, 3)}"
            if score >= min_score:
                out.append(Doubt(i, "tabela", _frac(el, lay), why + " Está certo?", score,
                                 (("Sim, é tabela", None), ("Não, é texto", "text"), ("É uma imagem", "figure")), tag))
        elif len(inside) >= 12:
            score = min(1.0, 0.4 + len(inside) / 80.0)
            out.append(Doubt(i, "figura_com_texto", _frac(el, lay), "Esta região foi tratada como imagem, mas tem bastante texto. O que é?",
                             score, (("É uma imagem", None), ("É texto", "text"), ("É uma tabela", "table")), "fig_texto"))
    return out


def find_doubts(engine, p, pages=None, limit: int = 120, progress=None, cancel=None) -> list[Doubt]:
    """Percorre as páginas (todas por padrão) e devolve as dúvidas mais fortes primeiro."""
    pages = list(pages) if pages is not None else list(range(engine.n))
    found: list[Doubt] = []
    for k, i in enumerate(pages):
        if cancel and cancel():
            break
        try:
            found += find_doubts_page(engine, i, p)
        except Exception:
            pass
        if progress:
            progress(k + 1, len(pages))
    found.sort(key=lambda d: -d.score)
    return found[:limit]


def answer_edit(d: Doubt, kind: str | None):
    """Edit correspondente à resposta (None = manter como está, sem edição)."""
    if kind is None:
        return None
    x0, y0, x1, y1 = d.rect
    return Edit(kind, x0, y0, x1, y1, scope="page", page=d.page)


# ------------------------------------------------------------------ dúvidas parecidas e respostas guardadas
def similar(a: Doubt, b: Doubt) -> bool:
    """b é parecida com a: mesmo tipo e formato/posição aproximados (a resposta de uma serve para a outra)."""
    if a.kind != b.kind or a.tag != b.tag:
        return False
    wa, ha = a.rect[2] - a.rect[0], a.rect[3] - a.rect[1]
    wb, hb = b.rect[2] - b.rect[0], b.rect[3] - b.rect[1]
    return abs(wa - wb) < 0.2 and abs(ha - hb) < 0.2 and abs(a.rect[0] - b.rect[0]) < 0.15


def _key(d: Doubt) -> str:
    return f"{d.page}:{d.rect[0]:.2f}:{d.rect[1]:.2f}:{d.kind}"


def load_confirmed(path) -> set:
    import json
    from pathlib import Path
    try:
        return set(json.loads(Path(path).read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_confirmed(path, keys: set):
    import json
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(sorted(keys), ensure_ascii=False), encoding="utf-8")
