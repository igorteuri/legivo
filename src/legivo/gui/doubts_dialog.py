"""Revisão de dúvidas: o programa pergunta, o usuário responde; respostas parecidas são aplicadas em lote."""
from __future__ import annotations
import traceback

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QProgressBar)

from ..core import doubts as D
from .views import OriginalView


class FindThread(QThread):
    progress = Signal(int, int)
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, engine, params):
        super().__init__()
        self.engine, self.params = engine, params
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            res = D.find_doubts(self.engine, self.params, progress=lambda a, b: self.progress.emit(a, b), cancel=lambda: self._cancel)
            self.done.emit(res)
        except Exception:
            self.failed.emit(traceback.format_exc())


class DoubtsDialog(QDialog):
    def __init__(self, parent, engine, params, confirmed_path, apply_edits):
        """apply_edits(lista de Edit): grava as respostas no documento (feito pela janela principal)."""
        super().__init__(parent)
        self.setWindowTitle("Revisar dúvidas")
        self.resize(900, 820)
        self.engine, self.params, self.cpath, self.apply_edits = engine, params, confirmed_path, apply_edits
        self.confirmed = D.load_confirmed(confirmed_path)
        self.queue: list = []
        self.idx = 0
        self.answered = 0
        self.th = None
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 14, 16, 12); lay.setSpacing(10)

        self.lb_title = QLabel("Procurando pontos em que o programa não tem certeza…"); self.lb_title.setObjectName("cardTitle")
        self.pb = QProgressBar()
        self.lb_q = QLabel(""); self.lb_q.setWordWrap(True)
        self.view = OriginalView("")
        self.view.set_drawing(False)
        self.cur_rect = None
        self.view.edit_changed.connect(self._rect_moved)
        self.row = QHBoxLayout(); self.row.setSpacing(8)
        self.ck_sim = QCheckBox(); self.ck_sim.setChecked(True)
        self.lb_note = QLabel("Dica: arraste o retângulo (ou as alças nas bordas) para ajustar exatamente a região antes de responder. "
                              "Marque a caixa para responder de uma vez as dúvidas parecidas (mesmo tipo e tamanho).")
        self.lb_note.setObjectName("hint"); self.lb_note.setWordWrap(True)
        foot = QHBoxLayout()
        self.btn_skip = QPushButton("Pular"); self.btn_skip.clicked.connect(self._skip)
        close = QPushButton("Fechar"); close.clicked.connect(self.close)
        foot.addWidget(self.btn_skip); foot.addStretch(1); foot.addWidget(close)
        for w in (self.lb_title, self.pb, self.lb_q):
            lay.addWidget(w)
        lay.addWidget(self.view, 1); lay.addLayout(self.row); lay.addWidget(self.ck_sim); lay.addWidget(self.lb_note); lay.addLayout(foot)
        for w in (self.view, self.ck_sim, self.btn_skip, self.lb_note):
            w.setVisible(False)

        self.th = FindThread(engine, params)
        self.th.progress.connect(lambda a, b: (self.pb.setMaximum(b), self.pb.setValue(a)))
        self.th.done.connect(self._found)
        self.th.failed.connect(lambda tb: (self.lb_title.setText("Erro ao procurar dúvidas."), print(tb)))
        self.th.start()

    # ---------------------------------------------------------------- fila
    def _found(self, found):
        self.pb.setVisible(False)
        self.queue = [d for d in found if D._key(d) not in self.confirmed]
        if not self.queue:
            self.lb_title.setText("Nenhuma dúvida: o programa teve certeza em tudo que analisou.")
            return
        for w in (self.view, self.ck_sim, self.btn_skip, self.lb_note):
            w.setVisible(True)
        self._show()

    def _show(self):
        while self.idx < len(self.queue) and self.queue[self.idx] is None:
            self.idx += 1
        if self.idx >= len(self.queue):
            self.lb_title.setText(f"Pronto! {self.answered} resposta(s) aplicada(s).")
            self.lb_q.setText("Não há mais dúvidas na fila. Você pode fechar esta janela.")
            for w in (self.view, self.ck_sim, self.btn_skip, self.lb_note):
                w.setVisible(False)
            self._clear_buttons()
            return
        d = self.queue[self.idx]
        left = sum(q is not None for q in self.queue[self.idx:])
        self.lb_title.setText(f"Dúvida — página {d.page + 1}  ·  restam {left}")
        self.lb_q.setText(d.pergunta)
        g = self.engine.render_thumb(d.page, 760)
        qi = QImage(g.data, g.shape[1], g.shape[0], g.strides[0], QImage.Format_Grayscale8).copy()
        self.view.set_image(QPixmap.fromImage(qi))
        self.cur_rect = tuple(d.rect)
        self._draw_rect()
        self._clear_buttons()
        for label, kind in d.opcoes:
            b = QPushButton(label)
            if kind is None:
                b.setObjectName("primary")
            b.clicked.connect(lambda _=False, k=kind: self._answer(k))
            self.row.addWidget(b)
        self.row.addStretch(1)
        n = sum(1 for q in self.queue[self.idx + 1:] if q is not None and D.similar(d, q))
        self.ck_sim.setText(f"Aplicar a mesma resposta às {n} dúvida(s) parecida(s)" if n else "Não há outras dúvidas parecidas")
        self.ck_sim.setEnabled(n > 0); self.ck_sim.setChecked(n > 0)

    def _draw_rect(self):
        self.view.set_overlay([], [(0, "figure", *self.cur_rect)], False)
        self.view.set_selected(0)

    def _rect_moved(self, idx, x0, y0, x1, y1):
        self.cur_rect = (x0, y0, x1, y1)
        self._draw_rect()

    def _clear_buttons(self):
        while self.row.count():
            it = self.row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _answer(self, kind):
        d = self.queue[self.idx]
        targets = [d]
        if self.ck_sim.isChecked():
            targets += [q for q in self.queue[self.idx + 1:] if q is not None and D.similar(d, q)]
        d.rect = tuple(self.cur_rect or d.rect)          # região ajustada pelo usuário
        edits = []
        for t in targets:
            e = D.answer_edit(t, kind)
            if e is not None:
                edits.append(e)
            else:
                self.confirmed.add(D._key(t))          # "está certo": não pergunta de novo
        for t in targets[1:]:
            self.queue[self.queue.index(t)] = None
        self.queue[self.idx] = None
        self.answered += len(targets)
        if edits:
            self.apply_edits(edits)
        D.save_confirmed(self.cpath, self.confirmed)
        self._show()

    def _skip(self):
        self.queue[self.idx] = None
        self._show()

    def closeEvent(self, e):
        if self.th is not None and self.th.isRunning():
            self.th.cancel(); self.th.wait(3000)
        super().closeEvent(e)
