"""Janela "Sobrepor páginas": mostra várias páginas empilhadas, semitransparentes, para ver o que se repete
(cabeçalhos, rodapés, números de página) e desenhar áreas a excluir de uma vez."""
from __future__ import annotations
import traceback

import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QSpinBox,
                               QProgressBar, QCheckBox)

from ..core.edits import Edit
from .views import OriginalView

MAX_PAGES = 80


def pick_pages(n: int, mode: str, a: int, b: int) -> list[int]:
    """Índices (base 0) das páginas a sobrepor; no máximo MAX_PAGES, espalhadas de forma uniforme."""
    if mode == "odd":
        idx = list(range(0, n, 2))
    elif mode == "even":
        idx = list(range(1, n, 2))
    elif mode == "range":
        idx = list(range(max(0, a - 1), min(n, b)))
    else:
        idx = list(range(n))
    if len(idx) > MAX_PAGES:
        idx = [idx[round(k * (len(idx) - 1) / (MAX_PAGES - 1))] for k in range(MAX_PAGES)]
    return idx


class CompositeThread(QThread):
    progress = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, engine, pages):
        super().__init__()
        self.engine, self.pages = engine, pages
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            img = self.engine.overlay_composite(self.pages, progress=lambda a, b: self.progress.emit(a, b),
                                                cancel=lambda: self._cancel)
            self.done.emit(None if self._cancel else img)
        except Exception:
            self.failed.emit(traceback.format_exc())


class OverlayDialog(QDialog):
    def __init__(self, parent, engine, current_page: int, add_edit):
        """add_edit(kind, (x0, y0, x1, y1), scope): grava uma edição no documento (feito pela janela principal)."""
        super().__init__(parent)
        self.setWindowTitle("Sobrepor páginas")
        self.resize(900, 820)
        self.engine, self.add_edit = engine, add_edit
        self.th = None
        self.drawn: list = []
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 14, 16, 12); lay.setSpacing(10)

        info = QLabel("As páginas escolhidas são empilhadas com transparência. O que aparece <b>escuro e nítido</b> está no mesmo lugar "
                      "em muitas páginas (cabeçalho, rodapé, número de página, marca d’água); o texto do corpo vira uma mancha clara. "
                      "<b>Arraste sobre o que quiser excluir</b>: a exclusão vale para todas as páginas do tipo escolhido.")
        info.setWordWrap(True); info.setObjectName("muted")
        lay.addWidget(info)

        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(QLabel("Páginas:"))
        self.cb_mode = QComboBox(); self.cb_mode.setAccessibleName("Quais páginas sobrepor")
        for k, t in (("all", "Todas"), ("odd", "Só ímpares"), ("even", "Só pares"), ("range", "Intervalo")):
            self.cb_mode.addItem(t, k)
        self.sp_a = QSpinBox(); self.sp_b = QSpinBox()
        for sp in (self.sp_a, self.sp_b):
            sp.setRange(1, max(1, engine.n))
        self.sp_a.setValue(max(1, current_page + 1)); self.sp_b.setValue(min(engine.n, current_page + 20))
        self.lb_to = QLabel("até")
        self.cb_mode.currentIndexChanged.connect(self._mode)
        self.btn_go = QPushButton("Gerar sobreposição"); self.btn_go.setObjectName("primary"); self.btn_go.clicked.connect(self._generate)
        row.addWidget(self.cb_mode); row.addWidget(self.sp_a); row.addWidget(self.lb_to); row.addWidget(self.sp_b)
        row.addStretch(1); row.addWidget(self.btn_go)
        lay.addLayout(row)

        row2 = QHBoxLayout(); row2.setSpacing(8)
        row2.addWidget(QLabel("Excluir em:"))
        self.cb_scope = QComboBox(); self.cb_scope.setAccessibleName("Onde aplicar a exclusão")
        for k, t in (("all", "Todas as páginas"), ("odd", "Páginas ímpares"), ("even", "Páginas pares")):
            self.cb_scope.addItem(t, k)
        self.lb_info = QLabel(""); self.lb_info.setObjectName("muted")
        row2.addWidget(self.cb_scope); row2.addWidget(self.lb_info, 1)
        lay.addLayout(row2)

        self.view = OriginalView("Clique em “Gerar sobreposição”.")
        self.view.set_drawing(True)
        self.view.region_drawn.connect(self._drawn)
        lay.addWidget(self.view, 1)

        self.pb = QProgressBar(); self.pb.setVisible(False)
        self.lb_status = QLabel(""); self.lb_status.setObjectName("muted"); self.lb_status.setWordWrap(True)
        foot = QHBoxLayout()
        self.btn_undo = QPushButton("Desfazer última"); self.btn_undo.setEnabled(False); self.btn_undo.clicked.connect(self._undo)
        close = QPushButton("Fechar"); close.clicked.connect(self.close)
        foot.addWidget(self.btn_undo); foot.addWidget(self.lb_status, 1); foot.addWidget(close)
        lay.addWidget(self.pb); lay.addLayout(foot)
        self._mode()

    def _mode(self):
        r = self.cb_mode.currentData() == "range"
        for w in (self.sp_a, self.sp_b, self.lb_to):
            w.setVisible(r)
        m = self.cb_mode.currentData()
        if m in ("odd", "even"):
            self.cb_scope.setCurrentIndex(self.cb_scope.findData(m))
        elif m == "all":
            self.cb_scope.setCurrentIndex(self.cb_scope.findData("all"))

    def _generate(self):
        pages = pick_pages(self.engine.n, self.cb_mode.currentData(), self.sp_a.value(), self.sp_b.value())
        if not pages:
            self.lb_status.setText("Nenhuma página nesse intervalo."); return
        self.btn_go.setEnabled(False); self.pb.setVisible(True); self.pb.setMaximum(len(pages)); self.pb.setValue(0)
        self.lb_info.setText(f"{len(pages)} página(s)" + (" (amostra espalhada)" if len(pages) == MAX_PAGES else ""))
        self.th = CompositeThread(self.engine, pages)
        self.th.progress.connect(lambda a, b: self.pb.setValue(a))
        self.th.done.connect(self._done)
        self.th.failed.connect(lambda tb: (self.lb_status.setText("Erro ao gerar a sobreposição."), print(tb), self._end()))
        self.th.start()

    def _end(self):
        self.pb.setVisible(False); self.btn_go.setEnabled(True)

    def _done(self, img):
        self._end()
        if img is None:
            return
        qi = QImage(img.data, img.shape[1], img.shape[0], img.strides[0], QImage.Format_Grayscale8).copy()
        self.view.set_image(QPixmap.fromImage(qi))
        self.view.set_overlay([], [(k, "exclude", *r) for k, r in enumerate(self.drawn)], False)
        self.lb_status.setText("Arraste sobre cabeçalhos, rodapés ou números que se repetem.")

    def _drawn(self, x0, y0, x1, y1):
        if (x1 - x0) < 0.004 or (y1 - y0) < 0.004:
            return
        scope = self.cb_scope.currentData()
        self.add_edit("exclude", (x0, y0, x1, y1), scope)
        self.drawn.append((x0, y0, x1, y1))
        self.view.set_overlay([], [(k, "exclude", *r) for k, r in enumerate(self.drawn)], False)
        self.btn_undo.setEnabled(True)
        self.lb_status.setText(f"{len(self.drawn)} exclusão(ões) criada(s) ({self.cb_scope.currentText().lower()}).")

    def _undo(self):
        if self.drawn:
            self.drawn.pop()
            self.add_edit("undo", None, None)
            self.view.set_overlay([], [(k, "exclude", *r) for k, r in enumerate(self.drawn)], False)
            self.btn_undo.setEnabled(bool(self.drawn))

    def closeEvent(self, e):
        if self.th is not None and self.th.isRunning():
            self.th.cancel(); self.th.wait(3000)
        super().closeEvent(e)
