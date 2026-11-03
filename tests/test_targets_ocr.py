"""Testes de OCR, Calibre, aparelhos conectados e créditos."""
import io
import re
import sys
import zipfile
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from legivo import __version__, about  # noqa: E402
from legivo.core import ocr, targets  # noqa: E402
from legivo.core.engine import Engine  # noqa: E402
from legivo.core.epub import build_epub, has_text  # noqa: E402
from legivo.core.params import Params  # noqa: E402


# ------------------------------------------------------------------ PDF só de imagem
def make_scan(path, pages=2):
    """PDF só de imagem (sem camada de texto): páginas em branco com ruído leve."""
    doc = pymupdf.open()
    for _ in range(pages):
        pg = doc.new_page(width=595, height=842)
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 200, 280), False)
        pix.set_rect(pix.irect, (255,))
        pg.insert_image(pg.rect, stream=pix.tobytes("png"))
    doc.save(path)
    doc.close()


def fake_lines(dpi):
    """Linhas "reconhecidas": duas linhas de um parágrafo e um título, em px do render do OCR."""
    k = dpi / 72.0
    def box(x0, y0, x1, y1):
        return (x0 * k, y0 * k, x1 * k, y1 * k)
    return [
        {"box": box(80, 90, 400, 120), "text": "Um Titulo Reconhecido", "score": 0.99},
        {"box": box(80, 150, 500, 163), "text": "Esta linha foi reconhecida pelo OCR de teste", "score": 0.97},
        {"box": box(80, 165, 500, 178), "text": "e continua na linha seguinte do mesmo paragrafo.", "score": 0.97},
    ]


@pytest.fixture()
def scan_engine(tmp_path, monkeypatch):
    f = tmp_path / "scan.pdf"
    make_scan(str(f))
    e = Engine(); e.open(str(f))
    monkeypatch.setattr(ocr, "recognize", lambda img: fake_lines(e.ocr_dpi))
    return e


def test_scanned_pdf_is_detected(scan_engine):
    assert scan_engine.scanned_pages() == [0, 1]
    assert not has_text(scan_engine)


def test_ocr_feeds_the_epub(scan_engine, tmp_path):
    assert scan_engine.run_ocr(cache_path=tmp_path / "c.ocr.json") == 2
    assert has_text(scan_engine)
    z = zipfile.ZipFile(io.BytesIO(build_epub(scan_engine, Params())))
    body = " ".join(z.read(n).decode() for n in z.namelist() if n.startswith("OEBPS/text/"))
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))
    assert "Esta linha foi reconhecida pelo OCR de teste e continua na linha seguinte" in plain, "linhas do OCR viram um parágrafo"
    assert re.search(r"<h[123][^>]*>[^<]*Titulo Reconhecido", body), "o texto maior vira título"


def test_ocr_cache_roundtrip(scan_engine, tmp_path):
    cache = tmp_path / "x.ocr.json"
    scan_engine.run_ocr(cache_path=cache)
    e2 = Engine(); e2.open(scan_engine.path)
    assert e2.load_ocr(cache) and e2.ocr_enabled and set(e2.ocr_pages) == {0, 1}
    assert e2.ocr_pages[0][0]["text"] == "Um Titulo Reconhecido"


def test_ocr_can_be_cancelled(scan_engine):
    done = scan_engine.run_ocr(cancel=lambda: True)
    assert done == 2 or scan_engine.ocr_pages == {}, "cancelar antes de começar não reconhece nada"
    assert scan_engine.ocr_pages == {}


def test_page_with_text_layer_does_not_use_ocr(tmp_path, monkeypatch):
    f = tmp_path / "t.pdf"
    doc = pymupdf.open(); pg = doc.new_page()
    for k in range(20):
        pg.insert_text((60, 80 + k * 14), f"linha de texto real numero {k}", fontsize=10)
    doc.save(str(f))
    monkeypatch.setattr(ocr, "recognize", lambda img: (_ for _ in ()).throw(AssertionError("OCR não deveria rodar")))
    e = Engine(); e.open(str(f))
    assert e.scanned_pages() == [] and has_text(e)
    assert e.run_ocr() == 0


@pytest.mark.skipif(not ocr.available()[0], reason="RapidOCR não instalado")
def test_real_ocr_reads_accented_portuguese(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    font = next((p for p in (r"C:\Windows\Fonts\arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") if Path(p).exists()), None)
    if font is None:
        pytest.skip("sem fonte TrueType para desenhar o texto de teste")
    im = Image.new("RGB", (1400, 300), "white")
    ImageDraw.Draw(im).text((40, 60), "Ação, coração e informação são palavras", fill="black", font=ImageFont.truetype(font, 54))
    import numpy as np
    lines = ocr.recognize(np.array(im))
    text = " ".join(l["text"] for l in lines).lower()
    assert "ação" in text and "coração" in text and "informação" in text, text


# ------------------------------------------------------------------ Calibre e aparelhos
def test_find_devices_by_markers(tmp_path):
    kindle, kobo, usb = tmp_path / "K", tmp_path / "B", tmp_path / "U"
    for d in ("documents", "system"):
        (kindle / d).mkdir(parents=True)
    (kindle / "koreader").mkdir()
    (kobo / ".kobo").mkdir(parents=True)
    usb.mkdir()
    devs = targets.find_devices([(kindle, True), (kobo, True), (usb, True)])
    assert len(devs) == 2
    k = next(d for d in devs if d["kind"] == "kindle")
    assert k["koreader"] and k["dest"].endswith("documents") and "KOReader" in k["label"]
    b = next(d for d in devs if d["kind"] == "kobo")
    assert b["dest"] == str(kobo)


def test_copy_to_device(tmp_path):
    src = tmp_path / "livro.epub"; src.write_bytes(b"x" * 100)
    out = targets.copy_to_device(str(src), str(tmp_path / "doc" / "sub"))
    assert Path(out).read_bytes() == b"x" * 100 and Path(out).parent.name == "sub"


def test_find_calibre_in_custom_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(targets.shutil, "which", lambda n: None)
    d = tmp_path / "Calibre2"; d.mkdir()
    (d / "calibredb.exe").write_text(""); (d / "ebook-convert.exe").write_text("")
    c = targets.find_calibre([d])
    assert c and Path(c["calibredb"]).name == "calibredb.exe"
    monkeypatch.setattr(targets, "_calibre_dirs", lambda: [])
    assert targets.find_calibre([tmp_path / "vazio"]) is None


class _R:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def test_calibre_commands_and_messages(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(targets, "_run", lambda cmd, timeout: calls.append(cmd) or _R(0, "Added book ids: 5"))
    cal = {"calibredb": "calibredb", "ebook-convert": "ebook-convert"}
    ok, msg = targets.calibre_add(cal, "a.epub")
    assert ok and calls[-1] == ["calibredb", "add", "a.epub"]
    # biblioteca bloqueada pelo Calibre aberto -> mensagem clara, sem erro técnico
    monkeypatch.setattr(targets, "_run", lambda cmd, timeout: _R(1, "", "Another calibre program is running"))
    ok, msg = targets.calibre_add(cal, "a.epub")
    assert not ok and "Feche o Calibre" in msg
    # conversão: cria o arquivo de saída
    src = tmp_path / "l.epub"; src.write_bytes(b"e")
    def fake_convert(cmd, timeout):
        Path(cmd[2]).write_bytes(b"azw3"); calls.append(cmd); return _R(0)
    monkeypatch.setattr(targets, "_run", fake_convert)
    ok, out, msg = targets.calibre_convert(cal, str(src), "azw3")
    assert ok and out.endswith(".azw3") and "kindle_pw" in calls[-1]


# ------------------------------------------------------------------ créditos
def test_credits_name_author_and_k2pdfopt():
    txt = about.plain_text()
    assert "Igor Teuri" in txt and "K2pdfopt" in txt and "Willus.com" in txt and __version__ in txt
    for tech in ("PyMuPDF", "PySide6", "RapidOCR", "ONNX Runtime", "Calibre", "KOReader"):
        assert tech in txt
    assert "Igor Teuri" in about.credits_markdown()


def test_opds_server_serves_only_registered_files(tmp_path):
    import urllib.request, urllib.error
    f = tmp_path / "Meu Livro.epub"; f.write_bytes(b"EPUB" * 50)
    srv = targets.OpdsServer(port=0, host="127.0.0.1").start()
    try:
        srv.add(str(f))
        feed = urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/opds", timeout=5).read().decode()
        assert "Meu Livro" in feed and "opds-spec.org/acquisition" in feed
        assert urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/file/Meu%20Livro.epub", timeout=5).read() == b"EPUB" * 50
        for bad in ("/file/outro.epub", "/file/../x", "/qualquer"):
            with pytest.raises(urllib.error.HTTPError) as ei:
                urllib.request.urlopen(f"http://127.0.0.1:{srv.port}{bad}", timeout=5)
            assert ei.value.code == 404
    finally:
        srv.stop()


def test_calibre_library_info_is_read_only(tmp_path):
    import sqlite3
    (tmp_path / "metadata.db").touch()
    con = sqlite3.connect(tmp_path / "metadata.db"); con.execute("create table books (id integer)")
    con.executemany("insert into books values (?)", [(1,), (2,), (3,)]); con.commit(); con.close()
    before = (tmp_path / "metadata.db").read_bytes()
    assert targets.calibre_library_info(str(tmp_path)) == {"path": str(tmp_path), "books": 3}
    assert (tmp_path / "metadata.db").read_bytes() == before, "nunca altera o banco do Calibre"
    assert targets.calibre_library_info(str(tmp_path / "nao_existe")) is None


# ---- aviso de nova versão (sem rede: resposta simulada) ----
def test_update_version_comparison():
    from legivo.core.updates import is_newer, parse_version
    assert is_newer("v0.12.0", "0.11.6") and is_newer("1.0", "0.99.9") and is_newer("0.11.10", "0.11.9")
    assert not is_newer("0.11.6", "0.11.6") and not is_newer("0.11.5", "0.11.6")
    assert not is_newer("lixo", "0.11.6") and not is_newer("0.12.0", "lixo")
    assert parse_version("0.12.0-beta") < parse_version("0.12.0")        # versão de teste vale menos que a final


def test_update_ignores_drafts_and_prereleases():
    from legivo.core.updates import from_release
    assert from_release({"tag_name": "v9.0.0", "draft": True}) is None
    assert from_release({"tag_name": "v9.0.0", "prerelease": True}) is None
    assert from_release({"tag_name": "nada"}) is None and from_release("x") is None


def test_update_check_uses_release_and_never_raises():
    import io
    import json as _json
    from legivo.core.updates import check, fetch_latest

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    data = {"tag_name": "v0.20.0", "html_url": "https://github.com/x/y/releases/tag/v0.20.0", "body": "novidades",
            "assets": [{"name": "Legivo-Setup.exe", "browser_download_url": "https://x/y.exe", "size": 5}]}
    up = check("0.11.6", opener=lambda req, timeout: Resp(_json.dumps(data).encode()))
    assert up and up.version == "0.20.0" and up.assets[0]["name"] == "Legivo-Setup.exe" and "releases" in up.url
    assert check("0.20.0", opener=lambda req, timeout: Resp(_json.dumps(data).encode())) is None      # já é a mais nova

    def sem_rede(req, timeout):
        raise OSError("sem internet")
    assert fetch_latest("0.11.6", opener=sem_rede) is None
    assert fetch_latest("0.11.6", opener=lambda req, timeout: Resp(b"isto nao e json")) is None
