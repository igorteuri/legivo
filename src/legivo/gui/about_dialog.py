"""Tela "Sobre" com os créditos."""
from __future__ import annotations
import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser

from .. import __version__, about as A
from . import branding


def _rows(rows) -> str:
    out = ["<table cellspacing='0' cellpadding='4' width='100%'>"]
    for n, use, lic, author, url in rows:
        out.append(f"<tr><td><b><a href='{url}'>{html.escape(n)}</a></b><br/><span style='color:gray'>{html.escape(author)} · {html.escape(lic)}</span>"
                   f"</td><td>{html.escape(use)}</td></tr>")
    out.append("</table>")
    return "".join(out)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Sobre o {A.APP_NAME}")
        self.setMinimumSize(640, 620)
        lay = QVBoxLayout(self); lay.setContentsMargins(20, 18, 20, 16); lay.setSpacing(12)

        head = QHBoxLayout(); head.setSpacing(16)
        logo = QLabel(); logo.setPixmap(branding.logo_pixmap(84)); logo.setFixedSize(84, 84)
        col = QVBoxLayout(); col.setSpacing(2)
        t = QLabel(A.APP_NAME); t.setObjectName("appTitle")
        v = QLabel(f"Versão {__version__} · {A.TAGLINE}"); v.setObjectName("muted")
        by = QLabel(f"Desenvolvido por <b>{A.__author__}</b>")
        lic = QLabel(f"{A.COPYRIGHT}<br/>Licença: {A.LICENSE}"); lic.setObjectName("muted")
        for w in (t, v, by, lic):
            col.addWidget(w)
        head.addWidget(logo, 0, Qt.AlignTop); head.addLayout(col, 1)
        lay.addLayout(head)

        desc = QLabel(A.DESCRIPTION); desc.setWordWrap(True)
        lay.addWidget(desc)

        i = A.INSPIRATION
        body = (f"<h3>Inspiração</h3><p><b><a href='{i[4]}'>{i[0]}</a></b> — {html.escape(i[3])} ({i[2]}).<br/>{html.escape(i[1])}</p>"
                f"<h3>Tecnologias utilizadas</h3>{_rows(A.TECHNOLOGIES)}"
                f"<h3>Integrações, referências e ferramentas</h3>{_rows(A.OTHERS)}"
                f"<p style='color:gray'>Código-fonte: {A.REPOSITORY}. Os componentes acima pertencem aos seus autores e seguem as respectivas licenças.</p>")
        tb = QTextBrowser(); tb.setOpenExternalLinks(True); tb.setHtml(body)
        lay.addWidget(tb, 1)

        main = parent if hasattr(parent, "check_updates_now") else None
        if main is not None:
            row = QHBoxLayout()
            self.ck_upd = QCheckBox("Avisar quando houver versão nova (consulta o GitHub ao abrir o programa, uma vez por dia)")
            self.ck_upd.setChecked(main.check_updates)
            self.ck_upd.toggled.connect(lambda on: setattr(main, "check_updates", bool(on)))
            btn_now = QPushButton("Procurar agora"); btn_now.clicked.connect(lambda: main.check_updates_now(self))
            row.addWidget(self.ck_upd, 1); row.addWidget(btn_now)
            lay.addLayout(row)

        foot = QHBoxLayout()
        self.btn_copy = QPushButton("Copiar informações")
        self.btn_copy.setToolTip("Copia versão e créditos para a área de transferência (útil para pedir suporte)")
        self.btn_copy.clicked.connect(self._copy)
        close = QPushButton("Fechar"); close.setObjectName("primary"); close.clicked.connect(self.accept)
        foot.addWidget(self.btn_copy); foot.addStretch(1); foot.addWidget(close)
        lay.addLayout(foot)

    def _copy(self):
        QGuiApplication.clipboard().setText(A.plain_text())
        self.btn_copy.setText("Copiado!")
