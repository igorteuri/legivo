"""Visualizações: imagem ajustada à janela e original editável (desenhar, mover, redimensionar)."""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal, QRect, QRectF, QPoint
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import QLabel, QRubberBand, QSizePolicy

from .overlay import paint_rect

MIN_SIZE = 0.006   # tamanho mínimo de uma edição (fração da página)
HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
CURSORS = {"nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor, "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
           "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor, "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor}


class FitLabel(QLabel):
    """Mostra uma imagem sempre ajustada ao espaço disponível."""
    def __init__(self, placeholder: str):
        super().__init__(placeholder)
        self._pm: QPixmap | None = None
        self._ph = placeholder
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setObjectName("canvas")

    def set_image(self, pm: QPixmap | None):
        self._pm = pm
        self._refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def _refresh(self):
        if self._pm is None:
            self.setPixmap(QPixmap()); self.setText(self._ph)
        else:
            self.setPixmap(self._pm.scaled(max(10, self.width() - 4), max(10, self.height() - 4),
                                           Qt.KeepAspectRatio, Qt.SmoothTransformation))


class OriginalView(FitLabel):
    """Original com regiões detectadas e edições. Tudo em frações (0..1) da página."""
    region_drawn = Signal(float, float, float, float)       # ferramenta de desenho
    edit_changed = Signal(int, float, float, float, float)  # edição movida/redimensionada
    edit_selected = Signal(int)
    delete_requested = Signal(int)
    context_requested = Signal(dict, QPoint)

    def __init__(self, placeholder):
        super().__init__(placeholder)
        self.draw_enabled = False
        self.items: list = []        # (kind, x0, y0, x1, y1) detectados
        self.edits: list = []        # (idx, kind, x0, y0, x1, y1)
        self.show_detect = True
        self.visible_kinds = None   # None = todos
        self.hint = None            # retângulo temporário (sugestão em revisão)
        self.selected = -1
        self._start = None
        self._drag = None            # (modo, pos inicial, retângulo inicial)
        self._tmp = None             # retângulo provisório durante o arrasto
        self._band = QRubberBand(QRubberBand.Rectangle, self)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # -- dados
    def set_overlay(self, items, edits, show_detect):
        self.items, self.edits, self.show_detect = items, edits, show_detect
        if self.selected >= 0 and not any(e[0] == self.selected for e in edits):
            self.selected = -1
        self.update()

    def set_visible_kinds(self, kinds):
        self.visible_kinds = set(kinds) if kinds is not None else None
        self.update()

    def set_hint(self, rect):
        self.hint = rect
        self.update()

    def set_selected(self, idx: int):
        self.selected = idx
        self.update()

    def set_drawing(self, on: bool):
        self.draw_enabled = on
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    # -- geometria
    def _img_rect(self):
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return None
        return (self.width() - pm.width()) // 2, (self.height() - pm.height()) // 2, pm.width(), pm.height()

    def _px(self, rect):
        ox, oy, w, h = self._img_rect()
        return QRectF(ox + rect[0] * w, oy + rect[1] * h, (rect[2] - rect[0]) * w, (rect[3] - rect[1]) * h)

    def _frac(self, pos):
        ox, oy, w, h = self._img_rect()
        return (pos.x() - ox) / w, (pos.y() - oy) / h

    def _edit_rect(self, idx):
        if self._tmp is not None and self._drag and self._drag[3] == idx:
            return self._tmp
        for e in self.edits:
            if e[0] == idx:
                return e[2:6]
        return None

    def _handle_at(self, pos, rect):
        r = self._px(rect)
        pts = {"nw": r.topLeft(), "n": QPoint(int(r.center().x()), int(r.top())), "ne": r.topRight(),
               "e": QPoint(int(r.right()), int(r.center().y())), "se": r.bottomRight(),
               "s": QPoint(int(r.center().x()), int(r.bottom())), "sw": r.bottomLeft(),
               "w": QPoint(int(r.left()), int(r.center().y()))}
        for name, pt in pts.items():
            if abs(pos.x() - pt.x()) <= 7 and abs(pos.y() - pt.y()) <= 7:
                return name
        return None

    def _edit_at(self, pos):
        for e in reversed(self.edits):
            if self._px(self._edit_rect(e[0])).contains(pos):
                return e[0]
        return -1

    # -- desenho
    def paintEvent(self, e):
        super().paintEvent(e)
        if not self._img_rect():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self.show_detect:
            for kind, x0, y0, x1, y1 in self.items:
                if self.visible_kinds is None or kind in self.visible_kinds:
                    paint_rect(p, self._px((x0, y0, x1, y1)), kind)
        for idx, kind, *_ in self.edits:
            paint_rect(p, self._px(self._edit_rect(idx)), {"exclude": "exclude", "table": "table_edit", "text": "text_edit"}.get(kind, "figure"))
        if self.hint is not None:
            paint_rect(p, self._px(self.hint), "exclude")
        if self.selected >= 0 and self._edit_rect(self.selected) is not None:
            r = self._px(self._edit_rect(self.selected))
            p.setPen(QPen(QColor("black"), 1.5, Qt.DashLine)); p.setBrush(Qt.NoBrush); p.drawRect(r)
            p.setPen(QPen(QColor("black"), 1.5)); p.setBrush(QColor("white"))
            for pt in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight(),
                       QPoint(int(r.center().x()), int(r.top())), QPoint(int(r.center().x()), int(r.bottom())),
                       QPoint(int(r.left()), int(r.center().y())), QPoint(int(r.right()), int(r.center().y()))):
                p.drawRect(QRectF(pt.x() - 5, pt.y() - 5, 10, 10))
        p.end()

    # -- mouse
    def mousePressEvent(self, e):
        if not self._img_rect():
            return
        pos = e.position().toPoint()
        if e.button() == Qt.RightButton:
            fx, fy = self._frac(pos)
            if 0 <= fx <= 1 and 0 <= fy <= 1:
                self.context_requested.emit(self._hit(fx, fy, self._edit_at(pos)), e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        self.setFocus()
        if self.draw_enabled:
            self._start = pos
            self._band.setGeometry(QRect(pos, pos)); self._band.show()
            return
        if self.selected >= 0 and self._edit_rect(self.selected) is not None:
            h = self._handle_at(pos, self._edit_rect(self.selected))
            if h:
                self._drag = (h, pos, self._edit_rect(self.selected), self.selected); return
        idx = self._edit_at(pos)
        if idx != self.selected:
            self.selected = idx
            self.edit_selected.emit(idx)
        if idx >= 0:
            self._drag = ("move", pos, self._edit_rect(idx), idx)
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._start is not None:
            self._band.setGeometry(QRect(self._start, pos).normalized()); return
        if self._drag:
            mode, p0, r0, idx = self._drag
            _, _, w, h = self._img_rect()
            dx, dy = (pos.x() - p0.x()) / w, (pos.y() - p0.y()) / h
            x0, y0, x1, y1 = r0
            if mode == "move":
                dx = max(-x0, min(1 - x1, dx)); dy = max(-y0, min(1 - y1, dy))
                x0, x1, y0, y1 = x0 + dx, x1 + dx, y0 + dy, y1 + dy
            else:
                if "w" in mode: x0 = max(0.0, min(x1 - MIN_SIZE, x0 + dx))
                if "e" in mode: x1 = min(1.0, max(x0 + MIN_SIZE, x1 + dx))
                if "n" in mode: y0 = max(0.0, min(y1 - MIN_SIZE, y0 + dy))
                if "s" in mode: y1 = min(1.0, max(y0 + MIN_SIZE, y1 + dy))
            self._tmp = (x0, y0, x1, y1)
            self.update(); return
        if self._img_rect() and not self.draw_enabled:
            h = self._handle_at(pos, self._edit_rect(self.selected)) if self.selected >= 0 and self._edit_rect(self.selected) else None
            if h:
                self.setCursor(CURSORS[h])
            elif self._edit_at(pos) >= 0:
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if self._start is not None:
            a, b = self._start, e.position().toPoint()
            self._start = None; self._band.hide()
            if self._img_rect():
                cl = lambda v: max(0.0, min(1.0, v))
                (ax, ay), (bx, by) = self._frac(a), self._frac(b)
                x0, x1 = sorted((cl(ax), cl(bx))); y0, y1 = sorted((cl(ay), cl(by)))
                self.region_drawn.emit(x0, y0, x1, y1)
            return
        if self._drag:
            idx, tmp, old = self._drag[3], self._tmp, self._drag[2]
            self._drag, self._tmp = None, None
            if tmp is not None and any(abs(a - b) > 1e-4 for a, b in zip(tmp, old)):
                self.edit_changed.emit(idx, *tmp)
            self.update()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected >= 0:
            self.delete_requested.emit(self.selected)
        else:
            super().keyPressEvent(e)

    # -- o que existe sob o ponteiro (para o menu de contexto)
    def _hit(self, fx, fy, edit_idx):
        def inside(it):
            return it[1] <= fx <= it[3] and it[2] <= fy <= it[4]
        area = lambda it: (it[3] - it[1]) * (it[4] - it[2])
        cand = [it for it in self.items if it[0] in ("line", "fixed", "fig") and inside(it)]
        cols = [it for it in self.items if it[0] == "col" and inside(it)]
        return {"pos": (fx, fy), "edit": edit_idx,
                "item": min(cand, key=area) if cand else None,
                "col": min(cols, key=area) if cols else None}
