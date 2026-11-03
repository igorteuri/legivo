"""Medidas de qualidade do reconhecimento de uma página (sem gabarito humano).

Servem para comparar o reconhecimento antes e depois de uma mudança no motor. Tudo é calculado a partir da camada de texto do PDF:
cada trecho de texto (span) deveria terminar numa linha refluída; se cair numa figura, numa linha
"fixa" ou em lugar nenhum, é um sinal de problema.
"""
from __future__ import annotations
import time
import traceback

from .layout import Figure, Text


def _inside(cx, cy, r, pad=0):
    return r[0] - pad <= cx <= r[2] + pad and r[1] - pad <= cy <= r[3] + pad


def page_signature(engine, i: int, p, dev=None, boxes: bool = True) -> dict:
    """Assinatura de uma página: métricas (frações dos trechos de texto do PDF) + estrutura detectada.

    refluido   : trechos que caíram numa linha de texto que será refeita (o ideal é perto de 1)
    fixas_txt  : trechos em linhas "fixas" (tabela/colunas não separadas; viram imagem da linha)
    em_figura  : trechos dentro de figura que não é tabela (perdem o reflow)
    em_tabela  : trechos dentro de tabela detectada (de propósito)
    perdidas   : trechos que não ficaram em nenhum lugar (texto que sumiria)
    inversoes  : blocos lidos depois de outro mas que começam acima dele, na mesma faixa (ordem trocada)
    fragmentos : fração de linhas minúsculas (sintoma de colunas mal cortadas)
    nota       : 0-100 (100 = sem sinais de problema)
    """
    row: dict = {"erro": ""}
    t = time.perf_counter()
    try:
        lay = engine.layout(i, p)
        vec = engine.page_vec(i, p)
        lines = [l for el in lay.elements if isinstance(el, Text) for l in el.lines]
        texts = [el for el in lay.elements if isinstance(el, Text)]
        figs = [el for el in lay.elements if isinstance(el, Figure)]
        row["linhas"] = len(lines)
        row["colunas"] = len({(t.cx0 // 40, t.cx1 // 40) for t in texts if len(t.lines) >= 3})
        row["figuras"] = sum(not f.table for f in figs)
        row["tabelas"] = sum(bool(f.table) for f in figs)
        row["fixas"] = round(sum(l.kind == "fixed" for l in lines) / max(1, len(lines)), 3)
        row["fragmentos"] = round(sum(len(l.words) <= 1 and l.w < 6 * lay.lh for l in lines) / max(1, len(lines)), 3)
        spans = vec["words"] if vec else []
        row["spans_pdf"] = len(spans)
        c = {"refluido": 0, "fixas_txt": 0, "em_figura": 0, "em_tabela": 0, "perdidas": 0}
        for s in spans:
            cx, cy = (s[0] + s[2]) / 2, (s[1] + s[3]) / 2
            hit = next((l for l in lines if _inside(cx, cy, (l.x0, l.y0, l.x1, l.y1), 6)), None)
            if hit is not None:
                c["refluido" if hit.kind == "text" else "fixas_txt"] += 1
                continue
            fh = [f for f in figs if _inside(cx, cy, (f.x0, f.y0, f.x1, f.y1))]
            if fh:
                c["em_tabela" if all(f.table for f in fh) else "em_figura"] += 1
            else:
                c["perdidas"] += 1
        n = max(1, len(spans))
        for k, v in c.items():
            row[k] = round(v / n, 3)
        row["inversoes"] = reading_inversions(lay)
        if dev is not None:
            row["paginas_saida"] = len(engine.compose_pages([i], p, dev))
        pen = 70 * row["perdidas"] + 35 * row["em_figura"] + 25 * row["fixas"] + 25 * row["fragmentos"]
        if spans and not lines:
            pen += 40
        if len(figs) == 1 and not lines and (figs[0].x1 - figs[0].x0) >= 0.9 * lay.W and (figs[0].y1 - figs[0].y0) >= 0.9 * lay.H:
            pen, row["ilustracao"] = 0, 1          # página de arte inteira: tratada como uma figura, de propósito
        row["nota"] = round(max(0.0, 100.0 - pen), 1)
        if boxes:
            # estrutura em milésimos da página (para comparar e desenhar antes x depois)
            W, H = lay.W, lay.H
            nb = lambda x0, y0, x1, y1: [round(1000 * x0 / W), round(1000 * y0 / H), round(1000 * x1 / W), round(1000 * y1 / H)]
            row["elementos"] = [
                (["tabela" if el.table else "figura"] + nb(el.x0, el.y0, el.x1, el.y1)) if isinstance(el, Figure)
                else (["texto"] + nb(el.cx0, min(l.y0 for l in el.lines), el.cx1, max(l.y1 for l in el.lines)))
                for el in lay.elements]
    except Exception:
        row.update(erro=traceback.format_exc().strip().splitlines()[-1][:160], nota=0.0)
    row["tempo_s"] = round(time.perf_counter() - t, 2)
    return row


def _box(el):
    """Extensão da TINTA do bloco (não da coluna a que pertence)."""
    if isinstance(el, Figure):
        return el.x0, el.y0, el.x1, el.y1
    return min(l.x0 for l in el.lines), min(l.y0 for l in el.lines), max(l.x1 for l in el.lines), max(l.y1 for l in el.lines)


def reading_inversions(lay) -> int:
    """Pares de blocos em ordem de leitura suspeita (A lido antes de B):
    - mesma faixa horizontal e B começa antes do fim de A (parte de baixo lida antes da de cima);
    - B fica inteiro à ESQUERDA de A e começa praticamente na mesma altura (até 3 linhas abaixo do início
      de A): texto da coluna da direita lido antes da coluna da esquerda.
    Colunas lado a lado em ordem normal não contam."""
    boxes = [_box(el) for el in lay.elements]
    tol = 0.5 * lay.lh
    n = 0
    for k, a in enumerate(boxes):
        for b in boxes[k + 1:]:
            if min(a[2], b[2]) - max(a[0], b[0]) > tol and b[1] < a[3] - tol:
                n += 1
            elif b[2] <= a[0] and b[1] < a[1] + 3 * lay.lh and b[3] > a[1]:
                n += 1
    return n


def reason(r: dict) -> str:
    """Texto curto com a causa provável de uma nota baixa."""
    if r.get("ilustracao"):
        return "ilustração de página inteira (ok)"
    if r.get("erro"):
        return "erro: " + r["erro"]
    bits = []
    for k, label in (("perdidas", "texto perdido"), ("em_figura", "texto dentro de figura"),
                     ("fixas", "linhas fixas"), ("fragmentos", "fragmentos de linha")):
        if r.get(k, 0) >= 0.1:
            bits.append(f"{label} {r[k]:.0%}")
    if r.get("spans_pdf") and not r.get("linhas"):
        bits.append("nenhuma linha reconhecida")
    return "; ".join(bits) or "ok"


# Tolerâncias da comparação com a referência (referência aprovada). Mudou além disto = regressão (ou melhoria a aceitar).
TOL = {"refluido": 0.03, "perdidas": 0.02, "em_figura": 0.05, "nota": 3.0}


def compare(ref: dict, new: dict) -> tuple[list[str], list[str]]:
    """Compara duas assinaturas da mesma página. Devolve (piores, mudancas):
    piores   = regressões claras (a página ficou pior);
    mudancas = mudanças de estrutura (pode ser melhoria; exige aceitar a nova referência)."""
    worse, changed = [], []
    if new.get("erro") and not ref.get("erro"):
        worse.append(f"erro novo: {new['erro']}")
        return worse, changed
    if new.get("refluido", 0) < ref.get("refluido", 0) - TOL["refluido"]:
        worse.append(f"texto refluído caiu {ref['refluido']:.0%} -> {new['refluido']:.0%}")
    if new.get("perdidas", 0) > ref.get("perdidas", 0) + TOL["perdidas"]:
        worse.append(f"texto perdido subiu {ref['perdidas']:.0%} -> {new['perdidas']:.0%}")
    if new.get("em_figura", 0) > ref.get("em_figura", 0) + TOL["em_figura"]:
        worse.append(f"texto dentro de figura subiu {ref['em_figura']:.0%} -> {new['em_figura']:.0%}")
    if new.get("inversoes", 0) > ref.get("inversoes", 0):
        worse.append(f"ordem de leitura: inversões {ref.get('inversoes', 0)} -> {new['inversoes']}")
    if new.get("nota", 0) < ref.get("nota", 0) - TOL["nota"]:
        worse.append(f"nota caiu {ref['nota']} -> {new['nota']}")
    if new.get("inversoes", 0) < ref.get("inversoes", 0):
        changed.append(f"ordem de leitura: inversões {ref.get('inversoes', 0)} -> {new['inversoes']} (melhorou?)")
    for k in ("colunas", "figuras", "tabelas"):
        if new.get(k) != ref.get(k):
            changed.append(f"{k}: {ref.get(k)} -> {new.get(k)}")
    a, b = ref.get("paginas_saida"), new.get("paginas_saida")
    if a and b and abs(a - b) > max(1, 0.25 * a):
        changed.append(f"páginas de saída: {a} -> {b}")
    return worse, changed
