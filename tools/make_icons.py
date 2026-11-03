"""Gera legivo.png (512 px) e legivo.ico (16..256 px) a partir de src/legivo/assets/legivo.svg.
Uso: python tools/make_icons.py"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PIL import Image  # noqa: E402
from legivo.gui.branding import logo_pixmap, ASSETS  # noqa: E402


def main():
    QApplication.instance() or QApplication([])
    sizes = (16, 24, 32, 48, 64, 128, 256)
    imgs = {}
    for s in sizes + (512,):
        tmp = ASSETS / f"_tmp_{s}.png"
        logo_pixmap(s, 1.0).save(str(tmp), "PNG")
        imgs[s] = Image.open(tmp).convert("RGBA")
        tmp.unlink()
    imgs[512].save(ASSETS / "legivo.png")
    imgs[256].save(ASSETS / "legivo.ico", sizes=[(s, s) for s in sizes], append_images=[imgs[s] for s in sizes[:-1]])
    print("ícones gerados em", ASSETS)


if __name__ == "__main__":
    main()
