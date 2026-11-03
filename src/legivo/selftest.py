"""Autoteste do programa empacotado: python run_legivo.py --self-test saida.json

Confere se as bibliotecas e o OCR funcionam dentro do executável (o .exe não tem console,
então o resultado vai para um arquivo JSON).
"""
from __future__ import annotations
import json
import sys
import traceback


def run(out_path: str) -> int:
    res: dict = {"ok": True, "checks": {}}

    def check(name, fn):
        try:
            res["checks"][name] = fn()
        except Exception:
            res["ok"] = False
            res["checks"][name] = "ERRO: " + traceback.format_exc()[-400:]

    def versions():
        import numpy, PIL, pymupdf, PySide6
        out = {"numpy": numpy.__version__, "pillow": PIL.__version__, "pymupdf": pymupdf.__version__, "pyside6": PySide6.__version__}
        from PySide6 import QtSvg  # noqa: F401  (logo)
        return out

    def logo():
        from PySide6.QtWidgets import QApplication
        from legivo.gui import branding
        QApplication.instance() or QApplication([])
        return branding.logo_pixmap(32).width()

    def devices():
        from legivo.core.engine import load_devices
        return len(load_devices())

    def epub():
        import pymupdf
        from legivo.core.engine import Engine
        from legivo.core.epub import build_epub
        from legivo.core.params import Params
        import tempfile, os
        d = tempfile.mkdtemp(); f = os.path.join(d, "t.pdf")
        doc = pymupdf.open(); pg = doc.new_page()
        for k in range(15):
            pg.insert_text((60, 80 + k * 14), f"linha de teste do epub numero {k}", fontsize=10)
        doc.save(f)
        e = Engine(); e.open(f)
        return len(build_epub(e, Params()))

    def ocr():
        from legivo.core import ocr as o
        ok, why = o.available()
        if not ok:
            if "No module named" in why:
                return "ausente (versão lite, sem OCR)"       # esperado na versão lite
            raise RuntimeError("OCR indisponível: " + why)
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np
        font = None
        for p in (r"C:\Windows\Fonts\arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            try:
                font = ImageFont.truetype(p, 54); break
            except Exception:
                pass
        im = Image.new("RGB", (1400, 220), "white")
        ImageDraw.Draw(im).text((40, 50), "Ação, coração e informação", fill="black", font=font)
        text = " ".join(l["text"] for l in o.recognize(np.array(im)))
        if "coração" not in text.lower():
            raise RuntimeError("OCR não reconheceu o texto de teste: " + text)
        return text

    for name, fn in (("versoes", versions), ("logo", logo), ("dispositivos", devices), ("epub_bytes", epub), ("ocr", ocr)):
        check(name, fn)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "selftest.json"))
