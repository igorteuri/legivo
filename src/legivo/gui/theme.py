"""Sistema de design do Legivo: tokens semânticos (claro/escuro) e folha de estilos Qt.

Diretrizes aplicadas (UI/UX Pro Max): contraste >= 4,5:1 para texto, foco visível (2 px),
alvos de clique >= 32 px, espaçamento em múltiplos de 4/8, cor nunca é o único sinal,
modo escuro com tons dessaturados (não invertidos), hierarquia por tamanho/peso/espaço.
"""
from __future__ import annotations
from PySide6.QtGui import QColor, QPalette, QGuiApplication
from PySide6.QtCore import Qt

TOKENS = {
    "light": dict(
        bg="#F3F5F8", surface="#FFFFFF", surface_alt="#EAEEF3", canvas="#DCE1E9",
        border="#D3DAE3", border_strong="#9AA6B5", text="#18202B", muted="#4A5565", disabled="#7A8594",
        primary="#1F5FBF", primary_hover="#1A4FA0", primary_soft="#E2ECFC", on_primary="#FFFFFF",
        hover="#EEF2F7", pressed="#E0E6EE", danger="#B3261E", success="#17703F", warn_soft="#FFF3D6",
    ),
    "dark": dict(
        bg="#11151B", surface="#1A2028", surface_alt="#222A34", canvas="#0D1014",
        border="#323D4B", border_strong="#5A6778", text="#E7EBF1", muted="#A8B3C1", disabled="#78838F",
        primary="#78AEFF", primary_hover="#97C1FF", primary_soft="#1F3250", on_primary="#08162B",
        hover="#222B36", pressed="#2B3643", danger="#FF8F85", success="#6FD39A", warn_soft="#3B3220",
    ),
}

_current = {"mode": "light", "tokens": TOKENS["light"]}


def tokens() -> dict:
    return _current["tokens"]


def mode() -> str:
    return _current["mode"]


def system_mode() -> str:
    try:
        return "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
    except Exception:
        return "light"


def build_palette(t: dict) -> QPalette:
    p = QPalette()
    c = QColor
    p.setColor(QPalette.Window, c(t["bg"])); p.setColor(QPalette.WindowText, c(t["text"]))
    p.setColor(QPalette.Base, c(t["surface"])); p.setColor(QPalette.AlternateBase, c(t["surface_alt"]))
    p.setColor(QPalette.Text, c(t["text"])); p.setColor(QPalette.Button, c(t["surface"]))
    p.setColor(QPalette.ButtonText, c(t["text"])); p.setColor(QPalette.ToolTipBase, c(t["surface"]))
    p.setColor(QPalette.ToolTipText, c(t["text"])); p.setColor(QPalette.Highlight, c(t["primary"]))
    p.setColor(QPalette.HighlightedText, c(t["on_primary"])); p.setColor(QPalette.PlaceholderText, c(t["muted"]))
    p.setColor(QPalette.Link, c(t["primary"]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, c(t["disabled"]))
    return p


def build_qss(t: dict, arrow: str = "") -> str:
    return f"""
QWidget {{ color: {t['text']}; font-size: 10pt; }}
QMainWindow, QDialog, QWidget#root, QWidget#sidebarBody {{ background: {t['bg']}; }}
QScrollArea {{ border: none; background: {t['bg']}; }}
QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border_strong']}; padding: 6px 8px; }}

QLabel:disabled, QCheckBox:disabled {{ color: {t['disabled']}; }}
QFrame#card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
QFrame#toolbar {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
QFrame#infobar {{ background: {t['primary_soft']}; border: 1px solid {t['primary']}; border-radius: 10px; }}
QFrame#empty {{ background: {t['canvas']}; border: 2px dashed {t['border_strong']}; border-radius: 14px; }}
QLabel {{ background: transparent; }}
QLabel#appTitle {{ font-size: 16pt; font-weight: 700; }}
QLabel#cardTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#paneTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#muted, QLabel#hint {{ color: {t['muted']}; }}
QLabel#emptyTitle {{ font-size: 14pt; font-weight: 600; }}
QLabel#badge {{ background: {t['primary']}; color: {t['on_primary']}; border-radius: 11px;
               min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; font-weight: 700; }}
QLabel#canvas {{ background: {t['canvas']}; color: {t['muted']}; border: 1px solid {t['border']}; border-radius: 12px; }}
QLabel#status {{ color: {t['muted']}; padding: 2px 4px; }}

QPushButton {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border_strong']};
              border-radius: 8px; padding: 6px 12px; min-height: 22px; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:pressed {{ background: {t['pressed']}; }}
QPushButton:disabled {{ color: {t['disabled']}; background: {t['surface_alt']}; border-color: {t['border']}; }}
QPushButton:focus {{ border: 2px solid {t['primary']}; padding: 5px 11px; }}
QPushButton#primary {{ background: {t['primary']}; color: {t['on_primary']}; border: 1px solid {t['primary']};
                      font-weight: 600; min-height: 30px; }}
QPushButton#primary:hover {{ background: {t['primary_hover']}; }}
QPushButton#primary:disabled {{ background: {t['surface_alt']}; color: {t['disabled']}; border-color: {t['border']}; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; }}
QPushButton#ghost:hover {{ background: {t['hover']}; }}
QPushButton#disclosure {{ background: transparent; border: none; text-align: left; font-weight: 600; padding: 4px 2px; }}
QPushButton[seg="first"], QPushButton[seg="mid"], QPushButton[seg="last"] {{ border-radius: 0px; }}
QPushButton[seg="first"] {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}
QPushButton[seg="last"] {{ border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}
QPushButton[seg]:checked {{ background: {t['primary_soft']}; color: {t['primary']}; border: 1px solid {t['primary']}; font-weight: 600; }}

QComboBox, QSpinBox, QDoubleSpinBox {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border_strong']};
              border-radius: 8px; padding: 4px 8px; min-height: 24px; }}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 2px solid {t['primary']}; padding: 3px 7px; }}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ background: {t['surface_alt']}; color: {t['disabled']}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0px; border: none; }}
QComboBox {{ combobox-popup: 0; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 12px; }}
QPushButton::menu-indicator {{ image: none; width: 0px; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; color: {t['text']}; selection-background-color: {t['primary_soft']};
              selection-color: {t['text']}; border: 1px solid {t['border_strong']}; outline: none; }}

QCheckBox {{ spacing: 8px; padding: 3px 0; }}
QCheckBox:focus {{ color: {t['primary']}; }}
QGroupBox {{ border: 1px solid {t['border']}; border-radius: 10px; margin-top: 10px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}


QSlider {{ min-height: 30px; }}
QSlider::groove:horizontal {{ height: 8px; background: {t['border']}; border-radius: 4px; }}
QSlider::sub-page:horizontal {{ background: {t['primary']}; border-radius: 4px; }}
QSlider::add-page:horizontal {{ background: {t['border']}; border-radius: 4px; }}
QSlider::handle:horizontal {{ background: {t['surface']}; border: 2px solid {t['primary']}; width: 18px; height: 18px;
              margin: -7px 0; border-radius: 11px; }}
QSlider::handle:horizontal:hover {{ background: {t['primary_soft']}; }}
QSlider::handle:horizontal:pressed {{ background: {t['primary']}; }}
QSlider::groove:horizontal:disabled, QSlider::add-page:horizontal:disabled {{ background: {t['surface_alt']}; }}
QSlider::sub-page:horizontal:disabled {{ background: {t['border_strong']}; }}
QSlider::handle:horizontal:disabled {{ background: {t['surface_alt']}; border: 2px solid {t['border_strong']}; }}

QListWidget {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 2px; outline: none; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {t['primary_soft']}; color: {t['text']}; }}
QListWidget::item:hover {{ background: {t['hover']}; }}

QProgressBar {{ background: {t['border']}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {t['primary']}; border-radius: 4px; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border_strong']}; border-radius: 5px; min-height: 32px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border_strong']}; border-radius: 5px; min-width: 32px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}

QMenu {{ background: {t['surface']}; border: 1px solid {t['border_strong']}; padding: 6px; border-radius: 8px; }}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['primary_soft']}; color: {t['text']}; }}
QMenu::item:disabled {{ color: {t['disabled']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 8px; }}
QStatusBar {{ background: {t['bg']}; }}
QStatusBar::item {{ border: none; }}
QSplitter::handle {{ background: transparent; }}
"""


def _arrow_file(color: str) -> str:
    """Seta da lista suspensa: o Qt precisa de um arquivo de imagem; geramos um PNG na pasta temporária."""
    from pathlib import Path
    import tempfile
    from . import icons
    d = Path(tempfile.gettempdir()) / "legivo_ui"
    d.mkdir(exist_ok=True)
    f = d / f"arrow_{color.lstrip('#')}.png"
    if not f.exists():
        icons.pixmap("chevron_down", color, 12, 2.0).save(str(f))
    return f.as_posix()


def apply_theme(app, pref: str = "auto") -> str:
    """pref: 'auto' | 'light' | 'dark'. Devolve o modo efetivo."""
    m = system_mode() if pref == "auto" else pref
    t = TOKENS[m]
    _current["mode"], _current["tokens"] = m, t
    app.setPalette(build_palette(t))
    app.setStyleSheet(build_qss(t, _arrow_file(t['muted'])))
    return m
