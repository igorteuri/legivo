"""Logo e ícone do aplicativo (a partir de um único SVG)."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SVG = ASSETS / "legivo.svg"


def logo_pixmap(size: int = 64, dpr: float = 2.0) -> QPixmap:
    """Logo desenhada em `size` px lógicos (renderizada em size*dpr px físicos)."""
    px = max(1, int(size * dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    QSvgRenderer(str(SVG)).render(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(logo_pixmap(s, 1.0))
    return ic
