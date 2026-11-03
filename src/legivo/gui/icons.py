"""Ícones vetoriais desenhados em código (grade 24x24), recoloridos conforme o tema.
Nada de emoji: cada ícone é uma forma desenhada com traço arredondado."""
from __future__ import annotations
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath, QBrush


def _poly(p: QPainter, pts, close=False):
    path = QPainterPath(QPointF(*pts[0]))
    for x, y in pts[1:]:
        path.lineTo(x, y)
    if close:
        path.closeSubpath()
    p.drawPath(path)


def _folder(p, c): _poly(p, [(3, 6), (9, 6), (11, 8.5), (21, 8.5), (21, 19), (3, 19)], True)
def _chev_l(p, c): _poly(p, [(15, 5), (8, 12), (15, 19)])
def _chev_r(p, c): _poly(p, [(9, 5), (16, 12), (9, 19)])
def _chev_d(p, c): _poly(p, [(5, 9), (12, 16), (19, 9)])
def _chev_u(p, c): _poly(p, [(5, 15), (12, 8), (19, 15)])
def _cursor(p, c): _poly(p, [(6, 3), (6, 19), (10, 15), (13, 21), (15.5, 20), (12.5, 14), (18, 14)], True)
def _check(p, c): _poly(p, [(5, 12.5), (10, 17.5), (19, 7)])


def _close(p, c):
    _poly(p, [(6, 6), (18, 18)]); _poly(p, [(18, 6), (6, 18)])


def _exclude(p, c):
    pen = p.pen(); pen.setStyle(Qt.DashLine); p.setPen(pen)
    p.drawRoundedRect(QRectF(3.5, 3.5, 17, 17), 2, 2)
    pen.setStyle(Qt.SolidLine); p.setPen(pen)
    _poly(p, [(8.5, 8.5), (15.5, 15.5)]); _poly(p, [(15.5, 8.5), (8.5, 15.5)])


def _image(p, c):
    p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2, 2)
    p.drawEllipse(QPointF(8.5, 10), 1.6, 1.6)
    _poly(p, [(4, 18), (10, 12.5), (14, 16), (16.5, 13.5), (20, 17)])


def _undo(p, c):
    _poly(p, [(8, 4.5), (4, 9), (8, 13.5)])
    path = QPainterPath(QPointF(4, 9)); path.cubicTo(17, 7, 21, 16, 11, 19)
    p.drawPath(path)


def _trash(p, c):
    _poly(p, [(4, 6.5), (20, 6.5)]); _poly(p, [(9, 6.5), (9, 4), (15, 4), (15, 6.5)])
    _poly(p, [(6, 6.5), (7, 20), (17, 20), (18, 6.5)])


def _sparkle(p, c):
    _poly(p, [(12, 3), (14.2, 9.8), (21, 12), (14.2, 14.2), (12, 21), (9.8, 14.2), (3, 12), (9.8, 9.8)], True)


def _save(p, c):
    _poly(p, [(12, 4), (12, 15)]); _poly(p, [(7, 10.5), (12, 15.5), (17, 10.5)]); _poly(p, [(4, 19.5), (20, 19.5)])


def _sun(p, c):
    p.drawEllipse(QPointF(12, 12), 4, 4)
    for dx, dy in ((0, -1), (0, 1), (1, 0), (-1, 0), (.7, .7), (-.7, .7), (.7, -.7), (-.7, -.7)):
        _poly(p, [(12 + dx * 7, 12 + dy * 7), (12 + dx * 9.5, 12 + dy * 9.5)])


def _moon(p, c):
    a = QPainterPath(); a.addEllipse(QRectF(4.5, 4, 15, 15))
    b = QPainterPath(); b.addEllipse(QRectF(9.5, 1.5, 14, 14))
    p.setBrush(QBrush(c)); p.drawPath(a.subtracted(b))


def _info(p, c):
    p.drawEllipse(QPointF(12, 12), 9, 9); _poly(p, [(12, 11), (12, 17)])
    p.setBrush(QBrush(c)); p.drawEllipse(QPointF(12, 7.6), 1.1, 1.1)


def _page(p, c):
    _poly(p, [(6, 3.5), (14, 3.5), (18, 7.5), (18, 20.5), (6, 20.5)], True); _poly(p, [(14, 3.5), (14, 7.5), (18, 7.5)])
    _poly(p, [(9, 12), (15, 12)]); _poly(p, [(9, 15.5), (15, 15.5)])


def _grid(p, c):
    for x, y in ((4, 4), (13.5, 4), (4, 13.5), (13.5, 13.5)):
        p.drawRoundedRect(QRectF(x, y, 6.5, 6.5), 1.5, 1.5)


def _link(p, c):
    p.drawRoundedRect(QRectF(3.5, 9, 10, 6), 3, 3)
    p.drawRoundedRect(QRectF(10.5, 9, 10, 6), 3, 3)


DRAW = {"link": _link, "grid": _grid, "folder": _folder, "chevron_left": _chev_l, "chevron_right": _chev_r, "chevron_down": _chev_d,
        "chevron_up": _chev_u, "cursor": _cursor, "check": _check, "close": _close, "exclude": _exclude,
        "image": _image, "undo": _undo, "trash": _trash, "sparkle": _sparkle, "save": _save, "sun": _sun,
        "moon": _moon, "info": _info, "page": _page}


def pixmap(name: str, color: str = "#000000", size: int = 20, dpr: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(size / 24, size / 24)
    c = QColor(color)
    p.setPen(QPen(c, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); p.setBrush(Qt.NoBrush)
    DRAW[name](p, c)
    p.end()
    return pm


def icon(name: str, color: str = "#000000", size: int = 20) -> QIcon:
    return QIcon(pixmap(name, color, size))
