"""Testes da exportação para EPUB (PDFs sintéticos com camada de texto)."""
import io
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from legivo.core.edits import Edit  # noqa: E402
from legivo.core.engine import Engine  # noqa: E402
from legivo.core.epub import build_epub, has_text  # noqa: E402
from legivo.core.params import Params  # noqa: E402


def make_doc(path, pages=3):
    doc = pymupdf.open()
    for n in range(pages):
        pg = doc.new_page(width=595, height=842)
        pg.insert_text((60, 40), "CABECALHO REPETIDO", fontsize=9)
        if n == 0:
            pg.insert_text((60, 90), "Um Titulo Grande do Documento", fontsize=26)
        for c in range(2):                          # duas colunas, 30 linhas cada
            x = 60 + c * 260
            tag = "ESQUERDA" if c == 0 else "DIREITA"
            for k in range(30):
                pg.insert_text((x, 150 + k * 13.5), f"{tag} pagina {n + 1} linha {k + 1:02d} texto corrente", fontsize=10)
    doc.save(path)
    doc.close()


def plain(epub: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(epub))
    txt = ""
    for name in sorted(z.namelist()):
        if name.startswith("OEBPS/text/"):
            txt += re.sub(r"<[^>]+>", " ", z.read(name).decode("utf-8")) + " "
    return re.sub(r"\s+", " ", txt)


@pytest.fixture()
def eng(tmp_path):
    f = tmp_path / "d.pdf"
    make_doc(str(f))
    e = Engine(); e.open(str(f))
    return e


def test_epub_is_valid_package(eng):
    data = build_epub(eng, Params())
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.namelist()[0] == "mimetype" and z.read("mimetype") == b"application/epub+zip"
    for n in z.namelist():
        if n.endswith((".xhtml", ".opf", ".ncx", ".xml")):
            ET.fromstring(z.read(n))               # XML bem formado
    d = pymupdf.open(stream=data, filetype="epub")  # um leitor real consegue abrir
    assert d.page_count >= 1


def test_epub_reads_left_column_before_right(eng):
    t = plain(build_epub(eng, Params(), [0]))
    assert t.index("ESQUERDA pagina 1 linha 30") < t.index("DIREITA pagina 1 linha 01"), "coluna da esquerda vem toda antes"


def test_epub_title_becomes_heading(eng):
    data = build_epub(eng, Params(), [0])
    z = zipfile.ZipFile(io.BytesIO(data))
    body = "".join(z.read(n).decode() for n in z.namelist() if n.startswith("OEBPS/text/"))
    assert re.search(r"<h[12][^>]*>[^<]*Titulo Grande", body)


def test_epub_exclude_edit_removes_header(eng):
    assert "CABECALHO REPETIDO" in plain(build_epub(eng, Params(), [1]))
    eng.add_edit(Edit("exclude", 0.0, 0.0, 1.0, 0.09, scope="all"))
    assert "CABECALHO REPETIDO" not in plain(build_epub(eng, Params(), [1]))


def test_epub_rejoins_hyphenated_words(tmp_path):
    f = tmp_path / "h.pdf"
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    for k in range(12):
        pg.insert_text((60, 100 + k * 13.5), "linha de apoio para dar corpo ao paragrafo de teste do epub", fontsize=10)
    pg.insert_text((60, 300), "uma palavra internacio-", fontsize=10)
    pg.insert_text((60, 313.5), "nal quebrada e outra long-", fontsize=10)
    pg.insert_text((60, 327), "term com hifen verdadeiro long-term aqui.", fontsize=10)
    doc.save(str(f))
    e = Engine(); e.open(str(f))
    t = plain(build_epub(e, Params()))
    assert "internacional" in t, "hífen de quebra de linha é removido"
    assert "long-term" in t, "hífen verdadeiro (a palavra aparece composta no texto) é mantido"


def test_has_text_detects_scanned_pdf(tmp_path, eng):
    assert has_text(eng)
    f = tmp_path / "img.pdf"
    doc = pymupdf.open(); pg = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 100, 100), False); pix.set_rect(pix.irect, (128,))
    pg.insert_image(pg.rect, pixmap=pix); doc.save(str(f))
    e = Engine(); e.open(str(f))
    assert not has_text(e)


def make_table_doc(path):
    doc = pymupdf.open(); pg = doc.new_page(width=595, height=842)
    for k in range(10):
        pg.insert_text((60, 80 + k * 13.5), f"texto corrido antes da tabela numero {k} com varias palavras", fontsize=10)
    rows = [("Classe", "Dado", "Limite", "Magia"), ("Clerigo", "d8", "9", "sim"), ("Druida", "d8", "14", "sim"),
            ("Guerreiro", "d10", "9", "nao"), ("Ladino", "d6", "10", "nao"), ("Monge", "d4", "17", "nao")]
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            pg.insert_text((60 + c * 110, 300 + r * 16), cell, fontsize=10)
    for k in range(10):
        pg.insert_text((60, 460 + k * 13.5), f"texto corrido depois da tabela numero {k} com varias palavras", fontsize=10)
    doc.save(path)


def test_epub_builds_real_table_from_aligned_columns(tmp_path):
    f = tmp_path / "t.pdf"; make_table_doc(str(f))
    e = Engine(); e.open(str(f))
    z = zipfile.ZipFile(io.BytesIO(build_epub(e, Params())))
    body = "".join(z.read(n).decode() for n in z.namelist() if n.startswith("OEBPS/text/"))
    tabs = re.findall(r"<table>.*?</table>", body)
    assert len(tabs) == 1, "a tabela vira <table>, não imagem"
    rows = re.findall(r"<tr>(.*?)</tr>", tabs[0])
    cells = [re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<t[dh]>.*?</t[dh]>", rows[1])]
    assert len(rows) == 6 and cells == ["Clerigo", "d8", "9", "sim"], cells
    assert "<img" not in body.replace('<img src="../images/cover', "")


def test_ocr_words_feed_table_cells(tmp_path, monkeypatch):
    """Página de imagem: as palavras do OCR (com posição) montam as células da tabela."""
    from legivo.core import ocr
    from test_targets_ocr import make_scan
    f = tmp_path / "s.pdf"; make_scan(str(f), 1)
    e = Engine(); e.open(str(f))
    k = e.ocr_dpi / 72.0
    def words(y, row):
        return [{"t": t, "b": (x * k, y * k, (x + 40) * k, (y + 10) * k)} for x, t in zip((60, 170, 280, 390), row)]
    rows = [("Classe", "Dado", "Limite", "Magia"), ("Clerigo", "d8", "9", "sim"), ("Druida", "d8", "14", "sim"),
            ("Guerreiro", "d10", "9", "nao"), ("Ladino", "d6", "10", "nao")]
    lines = []
    for r, row in enumerate(rows):
        ws = words(300 + r * 16, row)
        lines.append({"box": (60 * k, (300 + r * 16) * k, 430 * k, (310 + r * 16) * k), "text": " ".join(row), "score": 0.9, "words": ws})
    monkeypatch.setattr(ocr, "recognize", lambda img: lines)
    e.run_ocr()
    from legivo.core.epub import _table_rows
    res = _table_rows(e.ocr_words(0), (50, 290, 470, 390))
    assert res is not None and res[1][1] == ["Clerigo", "d8", "9", "sim"], res
