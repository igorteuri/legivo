"""Janela "Conexões": Calibre (biblioteca), KOReader (rede) e aparelhos por USB."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QFileDialog, QLineEdit

from ..core import targets
from .widgets import Card


class ConnectionsDialog(QDialog):
    def __init__(self, parent, settings: dict, get_opds, set_opds, last_output=None):
        """settings: dicionário editável (chave auto_calibre). get_opds/set_opds: acesso ao servidor da janela principal."""
        super().__init__(parent)
        self.setWindowTitle("Conexões")
        self.setMinimumHeight(760)
        self.setMinimumWidth(700)
        self.settings, self.get_opds, self.set_opds, self.last_output = settings, get_opds, set_opds, last_output
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 16, 16, 14); lay.setSpacing(12)

        # ---------------- Calibre
        c = Card("Calibre")
        self.calibre = targets.find_calibre()
        self.lib = targets.calibre_library_path()
        self.lb_cal = QLabel(); self.lb_cal.setWordWrap(True)
        c.body.addWidget(self.lb_cal)
        self.ck_auto = QCheckBox("Adicionar à biblioteca do Calibre automaticamente depois de converter")
        self.ck_auto.setChecked(bool(settings.get("auto_calibre", False)))
        self.ck_auto.toggled.connect(lambda v: settings.__setitem__("auto_calibre", bool(v)))
        self.ck_auto.setToolTip("Usa o calibredb. Se o Calibre estiver aberto, a biblioteca fica bloqueada e o programa avisa.")
        row = QHBoxLayout()
        self.b_open_cal = QPushButton("Abrir o Calibre"); self.b_open_cal.clicked.connect(self._open_calibre)
        self.b_site = QPushButton("Baixar o Calibre (grátis)"); self.b_site.clicked.connect(self._site)
        row.addWidget(self.b_open_cal); row.addWidget(self.b_site); row.addStretch(1)
        c.body.addWidget(self.ck_auto); c.body.addLayout(row)
        lay.addWidget(c)
        self._refresh_calibre()

        # ---------------- KOReader por rede
        k = Card("KOReader por rede (Wi-Fi)")
        info = QLabel("O KOReader sabe abrir catálogos OPDS. O Legivo pode servir os seus arquivos convertidos nesse formato: "
                      "você liga o servidor aqui, cadastra o endereço uma vez no KOReader e baixa os livros pelo próprio aparelho. "
                      "Funciona com o computador e o aparelho na mesma rede Wi-Fi.")
        info.setWordWrap(True); info.setObjectName("muted")
        k.body.addWidget(info)
        self.b_srv = QPushButton(); self.b_srv.setObjectName("primary"); self.b_srv.clicked.connect(self._toggle_server)
        self.ed_url = QLineEdit(); self.ed_url.setReadOnly(True); self.ed_url.setAccessibleName("Endereço do catálogo OPDS")
        self.b_copy = QPushButton("Copiar endereço"); self.b_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.ed_url.text()))
        self.b_add = QPushButton("Disponibilizar o último arquivo convertido"); self.b_add.clicked.connect(self._add_last)
        self.b_pick = QPushButton("Disponibilizar outro arquivo…"); self.b_pick.clicked.connect(self._add_other)
        r1 = QHBoxLayout(); r1.addWidget(self.b_srv); r1.addStretch(1)
        r2 = QHBoxLayout(); r2.addWidget(self.ed_url, 1); r2.addWidget(self.b_copy)
        r3 = QHBoxLayout(); r3.addWidget(self.b_add); r3.addWidget(self.b_pick); r3.addStretch(1)
        self.lb_files = QLabel(); self.lb_files.setObjectName("muted"); self.lb_files.setWordWrap(True)
        self.lb_steps = QLabel("No KOReader: menu de busca (lupa) › Catálogo OPDS › + (adicionar) › cole o endereço › abra o catálogo e toque no livro para baixar.")
        self.lb_steps.setObjectName("hint"); self.lb_steps.setWordWrap(True)
        self.lb_warn = QLabel("Segurança: enquanto o servidor estiver ligado, qualquer aparelho da sua rede com esse endereço vê a lista de arquivos "
                              "disponibilizados (só eles, nada mais do computador). Desligue quando terminar. O Windows pode pedir permissão no firewall.")
        self.lb_warn.setObjectName("hint"); self.lb_warn.setWordWrap(True)
        for item in (r1, r2, r3):
            k.body.addLayout(item)
        for w in (self.lb_files, self.lb_steps, self.lb_warn):
            k.body.addWidget(w)
        lay.addWidget(k)
        self._refresh_server()

        # ---------------- USB
        u = Card("Aparelho por USB (Kindle, Kobo, KOReader)")
        ul = QLabel("Conecte o leitor por cabo e use “Enviar ou abrir com…” (rodapé da janela principal) para copiar o arquivo para a pasta certa.")
        ul.setWordWrap(True); ul.setObjectName("muted")
        self.lb_usb = QLabel(); self.lb_usb.setWordWrap(True)
        u.body.addWidget(ul); u.body.addWidget(self.lb_usb)
        lay.addWidget(u)
        devs = targets.find_devices()
        self.lb_usb.setText(("Conectado agora: " + "; ".join(d["label"] for d in devs)) if devs else "Nenhum aparelho conectado no momento.")

        foot = QHBoxLayout(); foot.addStretch(1)
        close = QPushButton("Fechar"); close.setObjectName("primary"); close.clicked.connect(self.accept); foot.addWidget(close)
        lay.addLayout(foot)

    # -- Calibre
    def _refresh_calibre(self):
        if not self.calibre:
            self.lb_cal.setText("✖ Calibre não encontrado neste computador. Ele é gratuito e permite converter para Kindle (AZW3/MOBI) e organizar a biblioteca.")
            self.ck_auto.setEnabled(False); self.b_open_cal.setEnabled(False)
            return
        info = targets.calibre_library_info(self.lib) if self.lib else None
        if info:
            self.lb_cal.setText(f"✔ Calibre encontrado. Biblioteca: {info['path']} ({info['books']} livros).")
        else:
            self.lb_cal.setText("✔ Calibre encontrado, mas não consegui ler a biblioteca dele (abra o Calibre uma vez e escolha uma biblioteca).")

    def _open_calibre(self):
        import subprocess
        exe = (self.calibre or {}).get("calibre")
        if exe:
            subprocess.Popen([exe], creationflags=targets.CREATE_NO_WINDOW)

    def _site(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl("https://calibre-ebook.com/download"))

    # -- servidor OPDS
    def _refresh_server(self):
        srv = self.get_opds()
        on = srv is not None
        self.b_srv.setText("Desligar o servidor" if on else "Ligar o servidor de rede")
        self.ed_url.setText(srv.url if on else "")
        self.ed_url.setPlaceholderText("Ligue o servidor para ver o endereço")
        for w in (self.ed_url, self.b_copy, self.b_add, self.b_pick):
            w.setEnabled(on)
        self.b_add.setEnabled(on and bool(self.last_output and Path(self.last_output).exists()))
        names = sorted(srv.files) if on else []
        self.lb_files.setText(("Disponíveis: " + ", ".join(names)) if names else ("Nenhum arquivo disponibilizado ainda." if on else ""))

    def _toggle_server(self):
        srv = self.get_opds()
        if srv is not None:
            self.set_opds(None)
        else:
            try:
                self.set_opds(targets.OpdsServer(port=8765).start())
            except OSError:
                try:
                    self.set_opds(targets.OpdsServer(port=0).start())
                except Exception as e:
                    self.lb_files.setText(f"Não consegui ligar o servidor: {e}")
                    return
            if self.last_output and Path(self.last_output).exists():
                self.get_opds().add(self.last_output)
        self._refresh_server()

    def _add_last(self):
        if self.get_opds() and self.last_output:
            self.get_opds().add(self.last_output)
        self._refresh_server()

    def _add_other(self):
        f, _ = QFileDialog.getOpenFileName(self, "Escolher arquivo", "", "Livros (*.epub *.pdf *.azw3 *.mobi)")
        if f and self.get_opds():
            self.get_opds().add(f)
        self._refresh_server()
