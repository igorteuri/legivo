"""Componentes visuais reutilizáveis: cartão, seção recolhível, faixa de aviso e estado vazio."""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QSlider, QStyle, QStyleOptionSlider

from . import icons, theme


class Card(QFrame):
    """Cartão com título e, opcionalmente, número do passo (1, 2, 3...)."""
    def __init__(self, title: str = "", step: int | None = None):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 14); lay.setSpacing(10)
        head = QHBoxLayout(); head.setSpacing(8)
        if step is not None:
            badge = QLabel(str(step)); badge.setObjectName("badge"); badge.setAlignment(Qt.AlignCenter)
            badge.setAccessibleName(f"Passo {step}")
            head.addWidget(badge)
        self.title = QLabel(title); self.title.setObjectName("cardTitle")
        head.addWidget(self.title); head.addStretch(1)
        lay.addLayout(head)
        self.body = QVBoxLayout(); self.body.setSpacing(8)
        lay.addLayout(self.body)

    def add(self, item):
        (self.body.addLayout if hasattr(item, "addWidget") and not isinstance(item, QWidget) else self.body.addWidget)(item)


class Collapsible(QWidget):
    """Seção que o usuário abre quando precisa (divulgação progressiva)."""
    toggled = Signal(bool)

    def __init__(self, title: str):
        super().__init__()
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
        self.btn = QPushButton(title); self.btn.setObjectName("disclosure"); self.btn.setCheckable(True)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setAccessibleName(title)
        self.body = QWidget(); self.body_lay = QVBoxLayout(self.body); self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body.setVisible(False)
        lay.addWidget(self.btn); lay.addWidget(self.body)
        self.btn.toggled.connect(self._toggle)
        self.refresh_icons()

    def _toggle(self, on: bool):
        self.body.setVisible(on)
        self.refresh_icons()
        self.toggled.emit(on)

    def refresh_icons(self):
        self.btn.setIcon(icons.icon("chevron_up" if self.btn.isChecked() else "chevron_down", theme.tokens()["muted"], 18))


class InfoBar(QFrame):
    """Aviso discreto (não rouba o foco): mensagem, uma ação e um botão para dispensar."""
    action = Signal()
    dismissed = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("infobar")
        lay = QHBoxLayout(self); lay.setContentsMargins(12, 8, 8, 8); lay.setSpacing(10)
        self.ico = QLabel(); self.ico.setFixedSize(22, 22)
        self.text = QLabel(); self.text.setWordWrap(True)
        self.btn_action = QPushButton(); self.btn_action.clicked.connect(self.action)
        self.btn_close = QPushButton(); self.btn_close.setObjectName("ghost"); self.btn_close.setAccessibleName("Dispensar aviso")
        self.btn_close.setToolTip("Dispensar"); self.btn_close.setFixedSize(32, 32)
        self.btn_close.clicked.connect(self._dismiss)
        lay.addWidget(self.ico); lay.addWidget(self.text, 1); lay.addWidget(self.btn_action); lay.addWidget(self.btn_close)
        self.setVisible(False)
        self.refresh_icons()

    def _dismiss(self):
        self.setVisible(False)
        self.dismissed.emit()

    def show_message(self, text: str, action_text: str):
        self.text.setText(text); self.btn_action.setText(action_text)
        self.setVisible(True)

    def refresh_icons(self):
        t = theme.tokens()
        self.ico.setPixmap(icons.pixmap("info", t["primary"], 22))
        self.btn_close.setIcon(icons.icon("close", t["muted"], 16))


class EmptyState(QFrame):
    """Estado vazio: explica o que fazer, em vez de mostrar uma tela em branco."""
    open_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("empty")
        lay = QVBoxLayout(self); lay.setAlignment(Qt.AlignCenter); lay.setSpacing(10)
        self.ico = QLabel(); self.ico.setAlignment(Qt.AlignCenter)
        title = QLabel("Arraste um PDF para cá"); title.setObjectName("emptyTitle"); title.setAlignment(Qt.AlignCenter)
        sub = QLabel("ou clique em “Abrir PDF”. Artigos, provas e livros de RPG ficam legíveis\n"
                     "no Kindle e em qualquer tela, com pré-visualização na hora.")
        sub.setObjectName("muted"); sub.setAlignment(Qt.AlignCenter)
        self.btn = QPushButton("  Abrir PDF…"); self.btn.setObjectName("primary"); self.btn.setMinimumWidth(180)
        self.btn.clicked.connect(self.open_requested)
        lay.addWidget(self.ico); lay.addWidget(title); lay.addWidget(sub); lay.addSpacing(6)
        lay.addWidget(self.btn, 0, Qt.AlignCenter)
        self.refresh_icons()

    def refresh_icons(self):
        t = theme.tokens()
        self.ico.setPixmap(icons.pixmap("page", t["muted"], 56))
        self.btn.setIcon(icons.icon("folder", t["on_primary"], 18))


class ClickSlider(QSlider):
    """Controle deslizante fácil de usar: clicar em qualquer ponto da trilha leva o botão até lá
    (e o arrasto continua); a roda do mouse só age com o controle em foco."""
    def __init__(self, *a):
        super().__init__(*a)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            opt = QStyleOptionSlider(); self.initStyleOption(opt)
            groove = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
            handle = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
            if not handle.contains(e.position().toPoint()):
                span = max(1, groove.width() - handle.width())
                pos = int(e.position().x() - groove.x() - handle.width() / 2)
                self.setValue(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), max(0, min(span, pos)), span))
        super().mousePressEvent(e)

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()
