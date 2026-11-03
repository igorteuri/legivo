"""Janela "Enviar ou abrir com…": Calibre, aparelho conectado (Kindle/Kobo/KOReader) e a pasta do arquivo."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QListWidget,
                               QListWidgetItem, QProgressBar, QFileDialog, QFrame)

from ..core import targets
from .widgets import Card


class _Job(QThread):
    done = Signal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:      # pragma: no cover
            self.done.emit((False, str(e)))


class SendDialog(QDialog):
    def __init__(self, parent, path: str):
        super().__init__(parent)
        self.setWindowTitle("Enviar ou abrir com…")
        self.setMinimumWidth(620)
        self.calibre = targets.find_calibre()
        self._job = None
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 16, 16, 14); lay.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(QLabel("Arquivo a enviar:"))
        self.cb_file = QComboBox(); self.cb_file.setMinimumWidth(320)
        self.cb_file.setAccessibleName("Arquivo a enviar")
        self.cb_file.addItem(Path(path).name, path)
        top.addWidget(self.cb_file, 1)
        self.btn_folder = QPushButton("Abrir a pasta"); self.btn_folder.clicked.connect(lambda: targets.reveal_in_folder(self.current()))
        top.addWidget(self.btn_folder)
        lay.addLayout(top)

        # --- Calibre
        c = Card("Calibre")
        if self.calibre:
            self.lb_cal = QLabel("Calibre encontrado neste computador."); self.lb_cal.setObjectName("muted")
        else:
            self.lb_cal = QLabel("Calibre não encontrado. É gratuito: calibre-ebook.com. Depois de instalar, abra esta janela de novo.")
            self.lb_cal.setObjectName("muted")
        self.lb_cal.setWordWrap(True); c.body.addWidget(self.lb_cal)
        row1 = QHBoxLayout()
        self.b_add = QPushButton("Adicionar à biblioteca"); self.b_add.clicked.connect(self._cal_add)
        self.b_view = QPushButton("Abrir no visualizador"); self.b_view.clicked.connect(self._cal_view)
        row1.addWidget(self.b_add); row1.addWidget(self.b_view)
        row2 = QHBoxLayout()
        self.b_azw3 = QPushButton("Converter para AZW3 (Kindle)"); self.b_azw3.clicked.connect(lambda: self._cal_convert("azw3"))
        self.b_azw3.setToolTip("Formato que o Kindle lê direto (Paperwhite e mais novos).")
        self.b_mobi = QPushButton("Converter para MOBI (Kindle antigo)"); self.b_mobi.clicked.connect(lambda: self._cal_convert("mobi"))
        row2.addWidget(self.b_azw3); row2.addWidget(self.b_mobi)
        c.body.addLayout(row1); c.body.addLayout(row2)
        for b in (self.b_add, self.b_view, self.b_azw3, self.b_mobi):
            b.setEnabled(bool(self.calibre))
            if not self.calibre:
                b.setToolTip("Instale o Calibre (calibre-ebook.com) para usar esta opção.")
        lay.addWidget(c)

        # --- aparelho
        d = Card("Aparelho conectado por USB (Kindle, Kobo, KOReader)")
        self.lst_dev = QListWidget(); self.lst_dev.setMaximumHeight(90); self.lst_dev.setAccessibleName("Aparelhos conectados")
        self.lb_dev = QLabel(); self.lb_dev.setObjectName("muted"); self.lb_dev.setWordWrap(True)
        row3 = QHBoxLayout()
        self.b_refresh = QPushButton("Procurar de novo"); self.b_refresh.clicked.connect(self._scan)
        self.b_copy = QPushButton("Copiar para o aparelho"); self.b_copy.setObjectName("primary"); self.b_copy.clicked.connect(self._copy)
        self.b_other = QPushButton("Escolher outra pasta…"); self.b_other.clicked.connect(self._copy_other)
        row3.addWidget(self.b_refresh); row3.addWidget(self.b_other); row3.addStretch(1); row3.addWidget(self.b_copy)
        d.body.addWidget(self.lst_dev); d.body.addWidget(self.lb_dev); d.body.addLayout(row3)
        lay.addWidget(d)

        tip = QLabel("Sem cabo? O KOReader também recebe livros por Wi-Fi (Calibre sem fio) e por SSH, e o Kindle recebe por "
                     "“Enviar para o Kindle” (e-mail ou aplicativo). Detalhes em docs/INTEGRACOES.md.")
        tip.setObjectName("hint"); tip.setWordWrap(True)
        lay.addWidget(tip)

        self.busy = QProgressBar(); self.busy.setRange(0, 0); self.busy.setVisible(False)
        self.status = QLabel(""); self.status.setWordWrap(True)
        lay.addWidget(self.busy); lay.addWidget(self.status)
        foot = QHBoxLayout(); foot.addStretch(1)
        close = QPushButton("Fechar"); close.clicked.connect(self.accept); foot.addWidget(close)
        lay.addLayout(foot)

        self.cb_file.currentIndexChanged.connect(self._update_hint)
        self._scan()

    # -- utilidades
    def current(self) -> str:
        return self.cb_file.currentData()

    def _set_busy(self, on: bool, msg: str = ""):
        self.busy.setVisible(on)
        if msg:
            self.status.setText(msg)
        cal = bool(self.calibre) and not on
        for b in (self.b_add, self.b_view, self.b_azw3, self.b_mobi):
            b.setEnabled(cal)
        self.b_copy.setEnabled(bool(getattr(self, "devs", [])) and not on)
        self.b_other.setEnabled(not on); self.b_refresh.setEnabled(not on)

    def _scan(self):
        self.lst_dev.clear()
        self.devs = targets.find_devices()
        for dv in self.devs:
            it = QListWidgetItem(dv["label"]); it.setData(Qt.UserRole, dv)
            self.lst_dev.addItem(it)
        if self.devs:
            self.lst_dev.setCurrentRow(0)
        self.b_copy.setEnabled(bool(self.devs))
        self._update_hint()

    def _update_hint(self, *_):
        if not self.devs:
            self.lb_dev.setText("Nenhum aparelho encontrado. Conecte o leitor por USB (no Kindle, feche o KOReader antes), "
                                "espere ele aparecer como unidade e clique em “Procurar de novo”.")
            return
        dv = self.lst_dev.currentItem().data(Qt.UserRole) if self.lst_dev.currentItem() else self.devs[0]
        ext = Path(self.current()).suffix.lower()
        msg = f"Destino: {dv['dest']}"
        if dv["kind"] == "kindle" and not dv["koreader"] and ext == ".epub":
            msg += "\nO Kindle não lê EPUB direto: converta para AZW3 no Calibre (acima) ou use o KOReader."
        elif dv["koreader"]:
            msg += "\nO KOReader lê EPUB e PDF; talvez seja preciso reabri-lo para listar o arquivo novo."
        self.lb_dev.setText(msg)

    # -- ações do Calibre
    def _cal_add(self):
        p = self.current()
        self._start(lambda: targets.calibre_add(self.calibre, p), "Adicionando ao Calibre…", self._after_add)

    def _after_add(self, res):
        self._set_busy(False, ("✔ " if res[0] else "✖ ") + res[1])

    def _cal_view(self):
        ok = targets.calibre_open_viewer(self.calibre, self.current())
        self.status.setText("Abrindo no visualizador do Calibre…" if ok else "Não encontrei o visualizador do Calibre.")

    def _cal_convert(self, fmt: str):
        p = self.current()
        self._start(lambda: targets.calibre_convert(self.calibre, p, fmt), f"Convertendo para {fmt.upper()} com o Calibre…", self._after_convert)

    def _after_convert(self, res):
        ok, out, msg = res
        if ok:
            self.cb_file.addItem(Path(out).name, out)
            self.cb_file.setCurrentIndex(self.cb_file.count() - 1)
        self._set_busy(False, ("✔ " if ok else "✖ ") + msg)

    # -- aparelho
    def _copy(self):
        it = self.lst_dev.currentItem()
        if it is None:
            return
        self._do_copy(it.data(Qt.UserRole)["dest"])

    def _copy_other(self):
        d = QFileDialog.getExistingDirectory(self, "Escolher a pasta de destino")
        if d:
            self._do_copy(d)

    def _do_copy(self, dest: str):
        try:
            out = targets.copy_to_device(self.current(), dest)
            self.status.setText(f"✔ Copiado para {out}. Ejete o aparelho com segurança antes de desconectar.")
        except Exception as e:
            self.status.setText(f"✖ Não consegui copiar: {e}")

    # -- execução em segundo plano
    def _start(self, fn, msg, after):
        self._set_busy(True, msg)
        self._job = _Job(fn)
        self._job.done.connect(after)
        self._job.start()

    def done(self, r):
        if self._job is not None and self._job.isRunning():
            self._job.wait(1000)
        super().done(r)
