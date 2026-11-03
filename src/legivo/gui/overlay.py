"""Estilo visual das regiões marcadas sobre o original + legenda.

Paleta de Okabe-Ito (segura para os tipos comuns de daltonismo). Além da cor, cada tipo
tem uma espessura/traçado/hachura própria, para nunca depender só da cor.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QRectF, QSize, Signal
from PySide6.QtGui import QColor, QPen, QBrush, QPainter, QPixmap, QIcon
from PySide6.QtWidgets import QWidget, QHBoxLayout, QCheckBox

# tipo -> (nome, cor, espessura, traçado, hachura, explicação)
STYLES = {
    "col":     ("Coluna", "#0072B2", 3.0, Qt.SolidLine, None,
                "Bloco de texto detectado (traço grosso azul)."),
    "line":    ("Linha", "#009E73", 1.2, Qt.SolidLine, None,
                "Cada linha de texto detectada (traço fino verde-azulado)."),
    "fixed":   ("Tabela", "#CC79A7", 2.0, Qt.DotLine, None,
                "Linha com grandes espaços (tabela). Não é reorganizada (traço pontilhado rosa)."),
    "fig":     ("Figura", "#E69F00", 3.0, Qt.DashLine, None,
                "Imagem ou gráfico detectado. Mantido inteiro (traço tracejado laranja)."),
    "exclude": ("Excluída", "#D55E00", 2.0, Qt.SolidLine, Qt.DiagCrossPattern,
                "Região que você mandou ignorar (hachura em xadrez vermelho-alaranjado)."),
    "figure":  ("Figura manual", "#E69F00", 3.0, Qt.SolidLine, Qt.BDiagPattern,
                "Região que você mandou tratar como figura (hachura diagonal laranja)."),
}
STYLES["table_edit"] = ("Tabela (sua edição)", "#CC79A7", 3.0, Qt.SolidLine, Qt.CrossPattern,
                       "Região que você mandou tratar como tabela (hachura em grade rosa).")
STYLES["text_edit"] = ("Texto (sua edição)", "#0072B2", 3.0, Qt.SolidLine, Qt.HorPattern,
                      "Região que você mandou tratar como texto (hachura horizontal azul).")
LEGEND_ORDER = ("col", "line", "fixed", "fig", "exclude", "figure")


def paint_rect(p: QPainter, r: QRectF, kind: str):
    name, color, width, dash, hatch, _ = STYLES[kind]
    c = QColor(color)
    if hatch is not None:
        fill = QColor(c); fill.setAlpha(45); p.fillRect(r, fill)
        hc = QColor(c); hc.setAlpha(150); p.fillRect(r, QBrush(hc, hatch))
    pen = QPen(c, width, dash)
    pen.setJoinStyle(Qt.MiterJoin)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    p.drawRect(r)


def swatch_pixmap(kind: str, w: int = 30, h: int = 18) -> QPixmap:
    pm = QPixmap(w * 2, h * 2); pm.setDevicePixelRatio(2); pm.fill(QColor("white"))
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, True)
    paint_rect(p, QRectF(2, 2, w - 4, h - 4), kind)
    p.end()
    return pm


class LegendBar(QWidget):
    """Legenda das marcações. Cada item liga/desliga a camada correspondente."""
    kinds_changed = Signal(set)

    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(12)
        self.boxes: dict[str, QCheckBox] = {}
        for n, kind in enumerate(LEGEND_ORDER):
            cb = QCheckBox(STYLES[kind][0]); cb.setChecked(kind != "line")   # linhas: desligado por padrão (menos ruído)
            cb.setIcon(QIcon(swatch_pixmap(kind, 26, 16))); cb.setIconSize(QSize(26, 16))
            cb.setToolTip(STYLES[kind][5] + " Clique para mostrar ou esconder.")
            cb.toggled.connect(self._changed)
            self.boxes[kind] = cb
            row.addWidget(cb)
        row.addStretch(1)

    def _changed(self, *_):
        self.kinds_changed.emit(self.visible_kinds())

    def visible_kinds(self) -> set:
        return {k for k, cb in self.boxes.items() if cb.isChecked()}
