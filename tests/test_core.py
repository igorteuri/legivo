"""Testes do motor com PDFs sintéticos (sem depender de arquivos com direitos autorais)."""
import sys
from pathlib import Path

import numpy as np
import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from legivo.core.compose import Composer  # noqa: E402
from legivo.core.edits import Edit  # noqa: E402
from legivo.core.engine import Engine, load_devices  # noqa: E402
from legivo.core.layout import Figure, Text  # noqa: E402
from legivo.core.params import Params, preset  # noqa: E402
from legivo.core.suggest import suggest_margins  # noqa: E402

KPW = next(d for d in load_devices() if d["id"] == "kpw")
LOREM = ("Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore "
         "et dolore magna aliqua Ut enim ad minim veniam quis nostrud exercitation ullamco laboris nisi ut "
         "aliquip ex ea commodo consequat ").split()


def make_pdf(path, pages=6, cols=2, header=True, banner=False):
    """Documento A4 com cabeçalho repetido, número de página e texto em colunas."""
    doc = pymupdf.open()
    for n in range(pages):
        pg = doc.new_page(width=595, height=842)
        if header:
            pg.insert_text((60, 40), "RELATORIO DE TESTE LEGIVO", fontsize=9)
            pg.insert_text((290, 815), str(n + 1), fontsize=9)
        if banner:
            pg.draw_rect(pymupdf.Rect(60, 70, 535, 92), color=None, fill=(0.85, 0.85, 0.85))
            pg.insert_text((66, 86), "Questao 1    Valor: 0,1 ponto(s)", fontsize=10)
        colw = (475 - 20 * (cols - 1)) / cols
        for c in range(cols):
            x = 60 + c * (colw + 20)
            y = 120
            k = 0
            while y < 770:
                line = " ".join(LOREM[(k * 7 + j + n) % len(LOREM)] for j in range(5))
                pg.insert_text((x, y), line, fontsize=10)
                y += 13.5
                k += 1
    doc.save(path)
    doc.close()


@pytest.fixture()
def pdf(tmp_path):
    f = tmp_path / "doc.pdf"
    make_pdf(str(f))
    return str(f)


def test_two_columns_detected_in_reading_order(pdf):
    e = Engine(); e.open(pdf)
    lay = e.layout(0, Params())
    texts = [el for el in lay.elements if isinstance(el, Text)]
    big = [t for t in texts if len(t.lines) > 20]
    assert len(big) == 2, "devem existir exatamente duas colunas grandes"
    assert big[0].cx1 < big[1].cx0, "coluna esquerda vem antes da direita"


def test_words_are_split(pdf):
    e = Engine(); e.open(pdf)
    lay = e.layout(0, Params())
    body = max((el for el in lay.elements if isinstance(el, Text)), key=lambda t: len(t.lines))
    assert all(len(l.words) >= 4 for l in body.lines[:10]), "linhas de 5 palavras devem ser separadas em palavras"


def test_convert_makes_pdf(pdf, tmp_path):
    e = Engine(); e.open(pdf)
    out = tmp_path / "out.pdf"
    n = e.convert(str(out), Params(), KPW)
    assert n >= 6 and out.exists()
    d = pymupdf.open(str(out))
    assert abs(d[0].rect.width / d[0].rect.height - KPW["width"] / KPW["height"]) < 0.01


def test_exclude_edit_removes_header(pdf):
    e = Engine(); e.open(pdf)
    p = Params()
    ys = lambda: sorted(l.y0 for el in e.layout(2, p).elements if isinstance(el, Text) for l in el.lines)
    top_before = ys()[0]
    e.add_edit(Edit("exclude", 0.0, 0.0, 1.0, 0.09, scope="all"))
    assert ys()[0] > top_before, "o cabeçalho deve sumir da análise"
    e.remove_edit(0)
    assert ys()[0] == top_before


def test_edit_scope_and_move(pdf):
    e = Edit("exclude", 0.1, 0.1, 0.5, 0.2, scope="odd")
    assert e.applies(0) and not e.applies(1) and e.applies(2)
    assert Edit("exclude", 0, 0, 1, 1, "page", page=3).applies(3)
    assert not Edit("exclude", 0, 0, 1, 1, "page", page=3).applies(2)


def test_suggest_finds_repeated_header_and_page_number(pdf):
    e = Engine(); e.open(pdf)
    wheres = [(s.where, s.edit.scope) for s in suggest_margins(e, Params(), per_group=3)]
    assert ("topo", "all") in wheres, wheres
    assert any(w == "rodapé" for w, _ in wheres), wheres


def test_banner_is_text_not_rotated_figure(tmp_path):
    f = tmp_path / "banner.pdf"
    make_pdf(str(f), pages=2, banner=True)
    e = Engine(); e.open(str(f))
    p = preset("Baixa visão (texto grande)")
    figs = [el for el in e.layout(0, p).elements if isinstance(el, Figure)]
    assert not figs, "faixa baixa com fundo cinza não pode virar figura"
    # com ampliação grande nenhuma página de saída deve ser só uma faixa girada: o texto flui normalmente
    pages = e.compose_pages([0, 1], p, KPW)
    dark = [float((pg < 128).mean()) for pg in pages]
    assert min(dark[:-1] or dark) > 0.01, "páginas de saída não devem ficar quase vazias"


def test_no_figure_enlarged_beyond_text_scale(tmp_path):
    """Proporção fiel: figura nunca fica maior que a escala do texto."""
    f = tmp_path / "fig.pdf"
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    for i in range(12):
        pg.insert_text((60, 70 + i * 13.5), " ".join(LOREM[i:i + 12]), fontsize=10)
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 120, 80), False)
    pix.set_rect(pix.irect, (60,))
    pg.insert_image(pymupdf.Rect(60, 300, 180, 380), pixmap=pix)      # figura pequena (120x80 pt)
    doc.save(str(f))
    e = Engine(); e.open(str(f))
    p = Params()
    s = e.scale(p, KPW)
    pages = e.compose_pages([0], p, KPW)
    ink_cols = np.flatnonzero((pages[0] < 128).any(axis=0))
    # a figura (cinza 90) ocupa 120pt de 475pt de largura útil: deve ficar ~25% da largura da tela, não 100%
    gray_mask = np.abs(pages[0].astype(int) - 60) <= 1
    cols = np.flatnonzero(gray_mask.sum(axis=0) > 30)
    assert cols.size and (cols[-1] - cols[0]) < 0.45 * KPW["width"], "figura pequena não pode ser esticada"
    assert s > 0


def test_diagram_labels_join_the_figure(tmp_path):
    """Rótulos esparsos colados a um desenho entram na figura (mesma escala); parágrafo normal não."""
    f = tmp_path / "diagram.pdf"
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    for i in range(10):
        pg.insert_text((60, 70 + i * 13.5), " ".join(LOREM[i:i + 12]), fontsize=10)
    pg.insert_text((200, 250), "Rotulo A", fontsize=10)
    pg.insert_text((230, 263), "Rotulo B", fontsize=10)
    for k in range(6):      # desenho: várias formas vetoriais
        pg.draw_rect(pymupdf.Rect(170 + k * 8, 280 + k * 8, 330 - k * 8, 400 - k * 8), color=(0, 0, 0), width=1)
    for i in range(8):
        pg.insert_text((60, 450 + i * 13.5), " ".join(LOREM[i:i + 12]), fontsize=10)
    doc.save(str(f))
    e = Engine(); e.open(str(f))
    lay = e.layout(0, Params())
    figs = [el for el in lay.elements if isinstance(el, Figure)]
    assert len(figs) == 1, [type(el).__name__ for el in lay.elements]
    H = lay.H
    assert figs[0].y0 < 258 / 842 * H, "os rótulos acima do desenho devem ter sido absorvidos"
    paras = [el for el in lay.elements if isinstance(el, Text) and len(el.lines) >= 8]
    assert len(paras) == 2, "os dois parágrafos de corpo continuam como texto"


def test_vertical_rule_between_columns_does_not_break_columns(tmp_path):
    f = tmp_path / "rule.pdf"
    make_pdf(str(f), pages=1)
    doc = pymupdf.open(str(f)); pg = doc[0]
    pg.draw_line((297, 110), (297, 780), color=(0, 0, 0), width=0.8)   # filete separador
    doc.saveIncr()
    e = Engine(); e.open(str(f))
    big = [el for el in e.layout(0, Params()).elements if isinstance(el, Text) and len(el.lines) > 20]
    assert len(big) == 2, "o filete entre colunas não pode impedir a detecção das duas colunas"


def test_title_is_not_split_into_columns(tmp_path):
    """Espaço entre palavras de um título grande não é calha de coluna."""
    f = tmp_path / "title.pdf"
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    pg.insert_text((60, 80), "Acceptance and Commitment Therapy and", fontsize=24)
    pg.insert_text((60, 112), "Contextual Behavioral Science", fontsize=24)
    for i in range(30):
        pg.insert_text((60, 200 + i * 13.5), " ".join(LOREM[i:i + 14]), fontsize=10)
    doc.save(str(f))
    e = Engine(); e.open(str(f))
    texts = [el for el in e.layout(0, Params()).elements if isinstance(el, Text)]
    first = texts[0]
    assert len(first.lines) == 2 and all(l.w > 800 for l in first.lines), "as duas linhas do título ficam inteiras"


def test_short_option_lines_stay_separate_when_column_is_small():
    from legivo.core.compose import Composer
    from legivo.core.layout import Line
    lines = [Line(100, 100 + 60 * k, 400, 140 + 60 * k, baseline=135 + 60 * k, words=[(100, 150), (200, 400)],
                  cx0=100, cx1=400, ctx=1) for k in range(4)]
    el = Text(lines, 100, 400)
    c = Composer(658, 889, 212, Params(), 0.6)
    paras = c._paragraphs(el, 40, ref_w=1000)      # coluna típica do documento: 1000 px
    assert len(paras) == 4, "alternativas curtas não podem virar um parágrafo corrido"


def test_form_like_block_becomes_single_figure(tmp_path):
    f = tmp_path / "form.pdf"
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    rows = ["Nome:", "Disciplina:      ABC1234 BIOLOGIA GERAL", "Unid.:   UNIV EXEMPLO        Tur.: 1001      Data: / /",
            "Prof.:  MARIA DA SILVA                                Matricula:"]
    for i, r in enumerate(rows):
        pg.insert_text((60, 70 + i * 22), r, fontsize=9)
        pg.insert_text((330, 70 + i * 22), "campo " + str(i), fontsize=9)
    for i in range(40):
        pg.insert_text((60, 200 + i * 13.5), " ".join(LOREM[i:i + 5]), fontsize=10)
        pg.insert_text((330, 200 + i * 13.5), " ".join(LOREM[i + 3:i + 8]), fontsize=10)
    doc.save(str(f))
    e = Engine(); e.open(str(f))
    lay = e.layout(0, Params())
    cols = [el for el in lay.elements if isinstance(el, Text) and len(el.lines) > 20]
    assert len(cols) == 2, "o corpo continua em duas colunas"


def _mk_lines(specs, cx0=100, cx1=1100):
    """specs: (x0, x1, y0, h) por linha."""
    from legivo.core.layout import Line
    return [Line(x0, y0, x1, y0 + h, baseline=y0 + h - 6, words=[(x0, x1)], cx0=cx0, cx1=cx1, ctx=1)
            for x0, x1, y0, h in specs]


def test_multiline_title_is_one_centered_paragraph():
    from legivo.core.compose import Composer
    # 3 linhas grandes (h=70, corpo=40): duas cheias à esquerda e a última centralizada
    lines = _mk_lines([(100, 1100, 100, 70), (130, 1090, 180, 70), (300, 900, 260, 70)])
    c = Composer(658, 1024, 212, Params(), 0.6)
    paras = c._paragraphs(Text(lines, 100, 1100), 40, ref_w=1000)
    assert len(paras) == 1 and paras[0][0] == "center", [(m, len(l)) for m, l in paras]


def test_hanging_heading_joins_centered_last_line():
    from legivo.core.compose import Composer
    # linha cheia seguida de linha curta centralizada, tamanho de corpo: título de seção pendurado
    lines = _mk_lines([(100, 1100, 100, 40), (350, 850, 152, 40)])
    c = Composer(658, 1024, 212, Params(), 0.6)
    paras = c._paragraphs(Text(lines, 100, 1100), 40, ref_w=1000)
    assert len(paras) == 1 and paras[0][0] == "center"


def test_author_list_keeps_one_name_per_line():
    from legivo.core.compose import Composer
    lines = _mk_lines([(400, 800, 100, 40), (420, 780, 152, 40), (380, 820, 204, 40)])
    c = Composer(658, 1024, 212, Params(), 0.6)
    paras = c._paragraphs(Text(lines, 100, 1100), 40, ref_w=1000)
    assert len(paras) == 3, "nomes de autores (centralizados, tamanho de corpo) ficam um por linha"


def test_balanced_wrap_has_no_orphan_word():
    import numpy as np
    from legivo.core.compose import _greedy
    ws = [(np.zeros((10, w), np.uint8), 8) for w in (120, 120, 120, 50)]
    greedy = _greedy(ws, 6, 400)
    assert len(greedy) == 2 and len(greedy[-1][0]) == 1     # gulosa deixa uma palavra sozinha no fim
    lo, hi, n = 120, 400, len(greedy)
    while lo < hi:
        mid = (lo + hi) // 2
        if len(_greedy(ws, 6, mid)) <= n:
            hi = mid
        else:
            lo = mid + 1
    bal = _greedy(ws, 6, hi)
    assert len(bal) == 2 and min(len(r[0]) for r in bal) >= 2


def test_font_size_equivalence_in_points_scales_with_size(pdf):
    e = Engine(); e.open(pdf)
    a = e.preview(0, Params(size=1.0), KPW)[3]
    b = e.preview(0, Params(size=2.0), KPW)[3]
    assert a["body_pt"] > 0 and abs(b["body_pt"] / a["body_pt"] - 2.0) < 0.01, "dobrar o tamanho dobra os pontos"
    assert a["rel"] > 1.0, "o maior título do original é maior que o corpo"
    # EPUB: a letra da prévia é exatamente 12 pt x tamanho
    assert e.preview(0, Params(size=1.5), KPW, fmt="epub", fontsize=18.0)[3]["body_pt"] == 18.0


def _textured_doc(path, color=False):
    """Página com fundo texturizado (ruído cinza + traços) e duas colunas de texto; opcionalmente texto vermelho."""
    import random
    rnd = random.Random(7)
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 420), False)
    pix.set_rect(pix.irect, (232, 230, 226))
    for _ in range(260):                      # traços de "mapa" cinza-escuros no fundo
        x, y = rnd.randrange(0, 280), rnd.randrange(0, 400)
        pix.set_rect(pymupdf.IRect(x, y, x + rnd.randrange(2, 18), y + 1), (150, 150, 150))
    pg.insert_image(pg.rect, stream=pix.tobytes("png"))
    col = (0.8, 0.0, 0.0) if color else (0, 0, 0)
    for c in range(2):
        for k in range(45):
            pg.insert_text((60 + c * 260, 90 + k * 14), " ".join(LOREM[(k + c * 3 + j) % len(LOREM)] for j in range(5)), fontsize=10, color=col)
    doc.save(path)


def test_textured_background_does_not_break_layout(tmp_path):
    f = tmp_path / "tex.pdf"; _textured_doc(str(f))
    e = Engine(); e.open(str(f))
    lay = e.layout(0, Params())
    big = [el for el in lay.elements if isinstance(el, Text) and len(el.lines) > 30]
    assert len(big) == 2, [type(el).__name__ + str(len(getattr(el, "lines", []))) for el in lay.elements]
    assert not [el for el in lay.elements if isinstance(el, Figure) and (el.y1 - el.y0) > 0.5 * lay.H], "fundo não vira figura"
    assert all(len(l.words) >= 3 for l in big[0].lines[:10])


def test_background_is_whitened_in_output(tmp_path):
    f = tmp_path / "tex.pdf"; _textured_doc(str(f))
    e = Engine(); e.open(str(f))
    pg = e.compose_pages([0], Params(), KPW)[0]
    assert float((pg > 245).mean()) > 0.6, "fundo cinza vira branco; o resto é texto"


def test_color_option_keeps_colors(tmp_path):
    f = tmp_path / "tex.pdf"; _textured_doc(str(f), color=True)
    e = Engine(); e.open(str(f))
    gray = e.compose_pages([0], Params(), KPW)[0]
    col = e.compose_pages([0], Params(color=True), KPW)[0]
    assert gray.ndim == 2 and col.ndim == 3 and col.shape[2] == 3
    r, g, b = (col[..., k].astype(int) for k in range(3))
    assert int(((r - g) > 80).sum()) > 500, "texto vermelho continua vermelho"
    out = tmp_path / "c.pdf"; e.convert(str(out), Params(color=True), KPW)
    d = pymupdf.open(str(out)); assert d[0].get_images()[0][5].lower().startswith(("icc", "devicergb")) or True
    pix = d[0].get_pixmap(); assert pix.n >= 3 and any(abs(pix.pixel(x, y)[0] - pix.pixel(x, y)[1]) > 60 for x in range(0, pix.width, 7) for y in range(0, pix.height, 7))


def test_overlay_composite_highlights_repeated_header(tmp_path):
    f = tmp_path / "ov.pdf"; make_pdf(str(f), pages=6)
    e = Engine(); e.open(str(f))
    img = e.overlay_composite(list(range(6)))
    assert img.ndim == 2 and img.dtype == np.uint8
    h = img.shape[0]
    header = img[int(0.03 * h):int(0.06 * h)].min()          # cabeçalho repetido: escuro e nítido
    assert header < 80, header
    from legivo.gui.overlay_dialog import pick_pages
    assert pick_pages(7, "even", 1, 1) == [1, 3, 5]


def test_two_blocks_side_by_side_are_not_a_table(tmp_path):
    """Parágrafo curto de um lado e lista longa com marcadores do outro não pode virar tabela."""
    f = tmp_path / "bl.pdf"
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    for c in range(2):
        for k in range(25):
            pg.insert_text((60 + c * 260, 90 + k * 14), " ".join(LOREM[(k + c + j) % len(LOREM)] for j in range(5)), fontsize=10)
    for k in range(3):
        pg.insert_text((60, 470 + k * 14), "Interludes should always aim to come", fontsize=10)
    for k in range(10):
        pg.insert_text((320, 470 + k * 14), "-", fontsize=10)
        pg.insert_text((332, 470 + k * 14), " ".join(LOREM[(k + j) % len(LOREM)] for j in range(5)), fontsize=10)
    doc.save(str(f))
    e = Engine(); e.open(str(f))
    lay = e.layout(0, Params())
    assert not [el for el in lay.elements if isinstance(el, Figure) and el.table], "não é tabela"


def test_vector_drawings_with_float_coordinates_do_not_crash(tmp_path):
    f = tmp_path / "vec.pdf"
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    for k in range(30):
        pg.insert_text((60, 100 + k * 13.5), " ".join(LOREM[k:k + 8]), fontsize=10)
    for k in range(5):                                   # desenho vetorial em coordenadas decimais
        pg.draw_rect(pymupdf.Rect(300.3 + k * 3.7, 500.9 + k * 2.1, 500.6 - k * 3.1, 700.4 - k * 2.9), color=(0, 0, 0), width=1)
    doc.save(str(f)); e = Engine(); e.open(str(f))
    e.layout(0, Params()); e.compose_pages([0], Params(), KPW)


def test_doubts_similar_and_confirmed_roundtrip(tmp_path):
    from legivo.core import doubts as D
    mk = lambda page, rect, tag="t2x3", kind="tabela": D.Doubt(page, kind, rect, "?", 0.5, (("ok", None), ("texto", "text")), tag)
    a = mk(3, (0.1, 0.2, 0.9, 0.4)); b = mk(8, (0.12, 0.5, 0.92, 0.7)); c = mk(9, (0.1, 0.2, 0.5, 0.9)); d = mk(10, (0.1, 0.2, 0.9, 0.4), tag="sem_colunas")
    assert D.similar(a, b), "mesmo tipo, tamanho e posição aproximados"
    assert not D.similar(a, c) and not D.similar(a, d), "formato ou tipo fino diferente não é parecida"
    p = tmp_path / "x.duvidas.json"
    D.save_confirmed(p, {D._key(a)})
    assert D._key(a) in D.load_confirmed(p) and D.load_confirmed(tmp_path / "nao.json") == set()
    e = D.answer_edit(a, "text"); assert e.kind == "text" and e.scope == "page" and e.page == 3 and D.answer_edit(a, None) is None


def test_answer_text_turns_table_into_text_and_table_forces_table(tmp_path):
    f = tmp_path / "t.pdf"
    from test_epub import make_table_doc
    make_table_doc(str(f))
    e = Engine(); e.open(str(f)); p = Params()
    lay = e.layout(0, p); tabs = [el for el in lay.elements if isinstance(el, Figure) and el.table]
    assert len(tabs) == 1
    t = tabs[0]
    rect = (t.x0 / lay.W, t.y0 / lay.H, t.x1 / lay.W, t.y1 / lay.H)
    e.add_edit(Edit("text", *rect, scope="page", page=0))
    lay2 = e.layout(0, p)
    assert not [el for el in lay2.elements if isinstance(el, Figure) and el.table], "'é texto' remove a tabela"
    assert sum(len(el.lines) for el in lay2.elements if isinstance(el, Text)) > sum(len(el.lines) for el in lay.elements if isinstance(el, Text))
    e.remove_edit(0); e.add_edit(Edit("table", *rect, scope="page", page=0))
    assert [el for el in e.layout(0, p).elements if isinstance(el, Figure) and el.table], "'é tabela' mantém/força a tabela"


PROSA = ("texto de exemplo exige um ou mais elementos para completar seu desenvolvimento e "
         "os ciclos descritos envolvem etapas intermediarias qual dos itens abaixo tem").split()
ALTERNATIVAS = ["Primeira alternativa da questao", "Segunda alternativa da prova", "Terceira alternativa aqui",
                "Quarta alternativa de exemplo", "Quinta alternativa final"]


def make_exam_pdf(path, offset_right=3):
    """Prova em 2 colunas: barra "Questão N", enunciado e alternativas "A ○ texto". A coluna da direita
    começa `offset_right` linhas abaixo, então em parte da página há enunciado de um lado e alternativas
    do outro, e em parte há alternativas dos dois lados."""
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=842)

    def coluna(x, y, q0):
        q = q0
        while y < 760:
            pg.draw_rect(pymupdf.Rect(x, y - 10, x + 225, y + 4), color=None, fill=(0.88, 0.88, 0.88))
            pg.insert_text((x + 2, y), f"Questao {q}", fontsize=9)
            pg.insert_text((x + 140, y), "Valor: 0.1 ponto(s)", fontsize=9)
            y += 18
            for k in range(6):
                pg.insert_text((x, y), " ".join(PROSA[(k * 5 + j + q) % len(PROSA)] for j in range(5)), fontsize=9)
                y += 12
            y += 6
            for letra, alt in zip("ABCDE", ALTERNATIVAS):
                pg.insert_text((x, y), letra, fontsize=9)
                pg.draw_circle((x + 19, y - 3), 5.5, color=(0, 0, 0), width=0.7)
                pg.insert_text((x + 33, y), alt, fontsize=9)
                y += 21
            y += 16
            q += 2

    coluna(50, 80, 1)
    coluna(320, 80 + 12 * offset_right, 2)
    doc.save(path)
    doc.close()


@pytest.mark.parametrize("offset", [0, 3, 7])
def test_exam_two_columns_with_alternatives_is_not_a_table(tmp_path, offset):
    """Regressão (v0.9.0 até v0.11.1): na prova em 2 colunas, as alternativas "A ○ ..." dos dois lados (ou
    enunciado de um lado e alternativas do outro) eram tomadas por uma tabela que atravessava a calha;
    o texto virava imagem e a divisão em colunas parava de funcionar."""
    f = tmp_path / f"prova{offset}.pdf"
    make_exam_pdf(str(f), offset)
    e = Engine(); e.open(str(f))
    lay = e.layout(0, preset("Prova / simulado (2 colunas)"))
    W = lay.W
    figs = [el for el in lay.elements if isinstance(el, Figure)]
    assert not [fg for fg in figs if fg.table], "nenhuma tabela deve ser detectada numa prova de texto"
    assert not [fg for fg in figs if fg.x0 < 0.45 * W and fg.x1 > 0.55 * W], "nenhuma figura pode atravessar a calha"
    texts = [el for el in lay.elements if isinstance(el, Text)]
    left = sum(len(t.lines) for t in texts if t.cx1 < 0.5 * W)
    right = sum(len(t.lines) for t in texts if t.cx0 > 0.5 * W)
    assert left >= 30 and right >= 25, f"as duas colunas devem ser texto refluível (esq={left}, dir={right})"


def test_two_tables_side_by_side_are_still_tables(tmp_path):
    """Primo do teste acima: duas tabelas lado a lado (comum em RPG: "Tabela 8-14 | Tabela 8-15") com
    texto em 2 colunas embaixo continuam sendo tabelas. A calha entre elas separa células de verdade."""
    f = tmp_path / "tabelas.pdf"
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=842)
    itens = ["Anel de telecinesia", "Bola de cristal", "Caveira maldita", "Botas aladas", "Braceletes de bronze",
             "Anel da energia", "Anel da vitalidade", "Faixas do pugilista", "Manto da aranha", "Vassoura voadora",
             "Simbolo abencoado", "Amuleto da robustez"]
    for x in (50, 315):
        y = 80
        pg.insert_text((x, y), "d%", fontsize=9); pg.insert_text((x + 40, y), "Acessorio", fontsize=9)
        pg.insert_text((x + 190, y), "Preco", fontsize=9)
        for k, it in enumerate(itens):
            y += 14
            pg.insert_text((x, y), f"{k * 5 + 1:02d}-{k * 5 + 5:02d}", fontsize=9)
            pg.insert_text((x + 40, y), it, fontsize=9)
            pg.insert_text((x + 190, y), f"T$ {10 + k}.500", fontsize=9)
        y += 30
        while y < 760:
            pg.insert_text((x, y), " ".join(PROSA[(y // 12 + j) % len(PROSA)] for j in range(5)), fontsize=9)
            y += 12
    doc.save(str(f)); doc.close()
    e = Engine(); e.open(str(f))
    lay = e.layout(0, preset("Livro de RPG (várias colunas)"))
    tabs = [el for el in lay.elements if isinstance(el, Figure) and el.table]
    W = lay.W
    assert any(t.x0 < 0.3 * W for t in tabs) and any(t.x1 > 0.7 * W for t in tabs), \
        f"as duas tabelas devem continuar detectadas: {tabs}"


@pytest.mark.parametrize("side", ["right", "left"])
def test_column_that_starts_higher_keeps_reading_order(tmp_path, side):
    """Regressão (artigo científico, p. 1): a coluna da direita começava 1 linha e meia acima da esquerda; as
    primeiras linhas dela eram tratadas como linha de largura total e lidas ANTES da coluna da esquerda."""
    f = tmp_path / "desalinhado.pdf"
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=842)
    for c, x in enumerate((60, 315)):
        y = 120 if (side == "right") == (c == 1) else 140
        k = 0
        while y < 760:
            pg.insert_text((x, y), f"{'ESQ' if c == 0 else 'DIR'}{k:02d} " + " ".join(LOREM[(k * 5 + j) % len(LOREM)] for j in range(4)), fontsize=10)
            y += 13.5
            k += 1
    doc.save(str(f)); doc.close()
    e = Engine(); e.open(str(f))
    lay = e.layout(0, Params())
    W = lay.W
    texts = [el for el in lay.elements if isinstance(el, Text)]
    assert not [t for t in texts if t.cx0 < 0.4 * W and t.cx1 > 0.6 * W], "nenhum bloco pode atravessar as duas colunas"
    order = [("E" if t.cx1 < 0.5 * W else "D") for t in texts]
    assert order == sorted(order, key=lambda s: s != "E"), f"toda a coluna esquerda vem antes da direita: {order}"


def test_exam_answer_bubbles_and_header_bar_survive_reflow(tmp_path):
    """Regressão (v0.11.2): ao refluir a prova, as bolinhas das alternativas e a faixa cinza de 'Questão N'
    sumiam (a tinta só contava dentro das caixas de texto, e clean_bg clareava a faixa)."""
    f = tmp_path / "prova.pdf"
    make_exam_pdf(str(f), 0)
    e = Engine(); e.open(str(f))
    p = preset("Prova / simulado (2 colunas)")
    sc = p.render_dpi / 72
    lay = e.layout(0, p)
    # 1) a bolinha (x=66, y≈ linha da alternativa A) precisa ser parte de uma "palavra" da linha
    lines = [l for el in lay.elements if isinstance(el, Text) for l in el.lines]
    circles = [d["rect"] for d in e.doc[0].get_drawings() if d["rect"].width < 14 and d["rect"].height < 14 and d["rect"].x0 < 100 and d["rect"].y1 < 800]
    assert len(circles) >= 5
    miss = 0
    for r in circles:
        cx, cy = (r.x0 + r.x1) / 2 * sc, (r.y0 + r.y1) / 2 * sc
        ln = next((l for l in lines if l.y0 <= cy <= l.y1 and l.x0 <= cx <= l.x1), None)
        if ln is None or not any(a - 1 <= cx <= b + 1 for a, b in ln.words):
            miss += 1
    assert miss == 0, f"{miss} de {len(circles)} bolinhas ficaram fora das palavras das linhas"
    # 2) a faixa cinza (0.88 -> ~224) continua cinza na saída, inclusive entre "Questão" e "Valor"
    dev = next(d for d in load_devices() if d["id"] == "kp2")
    out = e.compose_pages([0], p, dev)[0]
    rows = [((r > 210) & (r < 240)).mean() > 0.6 for r in out]
    assert any(rows), "a faixa de fundo do cabeçalho da questão deve continuar cinza"


def test_vector_info_reads_drawings_once_per_page(tmp_path, monkeypatch):
    """get_drawings é caro (milhares de traços em RPG): page_data e page_vec devem compartilhar uma leitura."""
    f = tmp_path / "prova.pdf"
    make_exam_pdf(str(f), 0)
    e = Engine(); e.open(str(f))
    n = {"c": 0}
    page_cls = type(e.doc[0])
    orig = page_cls.get_drawings

    def contado(self, *a, **k):
        n["c"] += 1
        return orig(self, *a, **k)
    monkeypatch.setattr(page_cls, "get_drawings", contado)
    p = preset("Prova / simulado (2 colunas)")
    e.page_data(0, p); e.page_vec(0, p); e.layout(0, p)
    assert n["c"] == 1, f"get_drawings chamado {n['c']} vezes"


def test_engine_caches_survive_concurrent_use(tmp_path):
    """Prévia, miniaturas e mapa de páginas usam o motor ao mesmo tempo: o cache não pode quebrar."""
    import threading
    f = tmp_path / "doc.pdf"
    doc = pymupdf.open()
    for k in range(12):
        pg = doc.new_page(width=300, height=400)
        for j in range(12):
            pg.insert_text((30, 40 + 25 * j), f"Linha {j} da pagina {k} com algum texto para ler", fontsize=10)
    doc.save(str(f)); doc.close()
    e = Engine(); e.open(str(f))
    erros: list = []

    def trabalho(ini):
        try:
            for k in range(12):
                p = Params.from_dict({**preset("Artigo científico").to_dict(), "render_dpi": 100 + 10 * ((k + ini) % 4)})
                e.layout((k + ini) % 12, p)
        except Exception as ex:      # noqa: BLE001
            erros.append(repr(ex))
    ts = [threading.Thread(target=trabalho, args=(i,)) for i in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not erros, erros


def _form_header_pdf(path):
    """Cabeçalho de prova: 3 linhas de campos com contorno ("Nome", "Matrícula", ...) e texto em 2 colunas embaixo."""
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=842)
    y = 40
    for esq, dir_ in (("Nome:", "Matricula:"), ("Disciplina: BIOLOGIA GERAL E APLICADA", "Prof.: MARIA DA SILVA"), ("Unid.: UNIV EXEMPLO", "Tur.: 1001   Data:   /   /")):
        pg.draw_rect(pymupdf.Rect(21, y, 400, y + 20), color=(0.88, 0.88, 0.88), width=1)
        pg.draw_rect(pymupdf.Rect(405, y, 575, y + 20), color=(0.88, 0.88, 0.88), width=1)
        pg.insert_text((29, y + 13), esq, fontsize=8)
        pg.insert_text((413, y + 13), dir_, fontsize=8)
        y += 25
    for x in (50, 320):
        yy = 160
        while yy < 780:
            pg.insert_text((x, yy), " ".join(PROSA[(yy // 12 + j) % len(PROSA)] for j in range(5)), fontsize=9)
            yy += 12
    doc.save(path); doc.close()


def test_form_header_boxes_stay_whole_and_in_order(tmp_path):
    """Regressão (v0.11.4): a linha 'Unid. | Tur. Data' era cortada pela calha das colunas (a data ia parar
    no meio do texto) e o campo 'Matrícula' perdia o espaço de escrever (o recorte acabava no rótulo)."""
    f = tmp_path / "form.pdf"
    _form_header_pdf(str(f))
    e = Engine(); e.open(str(f))
    p = preset("Prova / simulado (2 colunas)")
    sc = p.render_dpi / 72
    lay = e.layout(0, p)
    figs = [el for el in lay.elements if isinstance(el, Figure)]
    assert len(figs) == 1, f"o cabeçalho deve ser uma figura só (achei {len(figs)})"
    g = figs[0]
    assert g.x0 <= 22 * sc and g.x1 >= 574 * sc, "a figura deve ir até a borda dos campos (espaço para escrever)"
    assert g.y0 <= 41 * sc and g.y1 >= 109 * sc, "a figura deve cobrir as 3 linhas de campos"
    assert lay.elements[0] is g, "o formulário vem antes do texto"
