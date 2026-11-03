"""Interface gráfica do Legivo (PySide6): preview ao vivo do original e do resultado."""
from __future__ import annotations
import json, logging, sys, time, traceback, webbrowser
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, QObject, Signal, QRunnable, QThreadPool, QThread, QSize
from PySide6.QtGui import QImage, QPixmap, QAction, QKeySequence, QIcon, QGuiApplication, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QComboBox, QCheckBox,
    QSpinBox, QDoubleSpinBox, QVBoxLayout, QHBoxLayout, QFormLayout, QFileDialog, QSplitter,
    QScrollArea, QProgressBar, QMessageBox, QButtonGroup, QListWidget, QListWidgetItem,
    QDialog, QMenu, QFrame, QStackedWidget, QListView,
)

from ..core.engine import Engine, load_devices
from ..core.epub import export_epub, has_text
from ..core import ocr as ocrmod
from .. import __version__
from ..core.params import Params, PRESETS, preset
from ..core.edits import Edit, SCOPES
from ..core.suggest import suggest_margins
from . import theme, icons
from .overlay import LegendBar
from .views import FitLabel, OriginalView
from .widgets import Card, Collapsible, InfoBar, EmptyState, ClickSlider
from .about_dialog import AboutDialog
from .send_dialog import SendDialog
from .doubts_dialog import DoubtsDialog
from .overlay_dialog import OverlayDialog
from .connections_dialog import ConnectionsDialog
from ..core import targets, updates
from . import branding

APP_NAME = "Legivo"
log = logging.getLogger("legivo")
MAX_MAP_PAGES = 150     # acima disso a contagem de páginas de saída só aparece na conversão

PRESET_HELP = {
    "Artigo científico (2 colunas)": "Transforma as duas colunas em uma só, mantendo figuras e tabelas inteiras.",
    "Prova / simulado (2 colunas)": "Texto um pouco maior e mais espaçado, para questões e alternativas.",
    "Livro de RPG (várias colunas)": "Até 4 colunas, ignora fundos texturizados e mantém mapas e ilustrações como imagens.",
    "Baixa visão (texto grande)": "Ampliação grande, mais contraste e sem justificar, para ler com conforto.",
    "Só ajustar à tela (sem reorganizar)": "Apenas encaixa cada linha na largura da tela, sem refazer as quebras.",
}
FORMAT_HELP = {
    "pdf": "PDF com o layout refeito (cada palavra vira imagem). Funciona em qualquer leitor.",
    "epub": "Texto de verdade, reorganizado: o aparelho ajusta o tamanho da letra. Para o Kindle, envie o arquivo "
            "pelo “Enviar para o Kindle” (e-mail ou aplicativo), que converte o EPUB.",
}


def settings_path() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
    return base / "legivo_config.json"


def to_pixmap(arr: np.ndarray) -> QPixmap:
    arr = np.ascontiguousarray(arr)
    fmt = QImage.Format_Grayscale8 if arr.ndim == 2 else QImage.Format_RGB888
    return QPixmap.fromImage(QImage(arr.data, arr.shape[1], arr.shape[0], arr.strides[0], fmt).copy())


def icon2(name: str, off: str, on: str, size: int = 18) -> QIcon:
    ic = QIcon()
    ic.addPixmap(icons.pixmap(name, off, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(icons.pixmap(name, on, size), QIcon.Normal, QIcon.On)
    ic.addPixmap(icons.pixmap(name, theme.tokens()["disabled"], size), QIcon.Disabled, QIcon.Off)
    return ic


class Signals(QObject):
    done = Signal(int, object, object, object, object, float)
    failed = Signal(int, str)


class PreviewJob(QRunnable):
    def __init__(self, gen, engine, page, params, dev, fmt, fontsize, sig):
        super().__init__()
        self.gen, self.engine, self.page, self.params, self.dev, self.fmt, self.fontsize, self.sig = gen, engine, page, params, dev, fmt, fontsize, sig

    def run(self):
        try:
            t0 = time.perf_counter()
            small, items, outs, info = self.engine.preview(self.page, self.params, self.dev, fmt=self.fmt, fontsize=self.fontsize)
            self.sig.done.emit(self.gen, small, items, outs, info, time.perf_counter() - t0)
        except Exception:
            self.sig.failed.emit(self.gen, traceback.format_exc())


class UpdateSignals(QObject):
    found = Signal(object)       # updates.Update ou None
    finished = Signal()


class UpdateJob(QRunnable):
    """Consulta a última versão nas Releases do GitHub, fora da thread da interface."""
    def __init__(self, sig):
        super().__init__()
        self.sig = sig

    def run(self):
        try:
            self.sig.found.emit(updates.check(__version__))
        except Exception:
            self.sig.found.emit(None)
        self.sig.finished.emit()


class ConvertThread(QThread):
    progress = Signal(int, int)
    finished_ok = Signal(int, str)
    failed = Signal(str)

    def __init__(self, engine, dst, params, dev, fmt):
        super().__init__()
        self.engine, self.dst, self.params, self.dev, self.fmt = engine, dst, params, dev, fmt
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            cb = dict(progress=lambda a, b: self.progress.emit(a, b), cancel=lambda: self._cancel)
            if self.fmt == "epub":
                n = export_epub(self.engine, self.dst, self.params, **cb)
            else:
                n = self.engine.convert(self.dst, self.params, self.dev, None, **cb)
            self.finished_ok.emit(n, self.dst)
        except Exception:
            self.failed.emit(traceback.format_exc())


class SuggestThread(QThread):
    progress = Signal(int, int)
    result = Signal(list)
    failed = Signal(str)

    def __init__(self, engine, params):
        super().__init__()
        self.engine, self.params = engine, params

    def run(self):
        try:
            self.result.emit(suggest_margins(self.engine, self.params, progress=lambda a, b: self.progress.emit(a, b)))
        except Exception:
            self.failed.emit(traceback.format_exc())


class ThumbWorker(QThread):
    """Gera as miniaturas de todas as páginas em segundo plano."""
    thumb = Signal(int, QImage)

    def __init__(self, engine, n):
        super().__init__()
        self.engine, self.n = engine, n
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for i in range(self.n):
            if self._stop:
                return
            try:
                a = self.engine.render_thumb(i, 120)
            except Exception:
                continue
            self.thumb.emit(i, QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format_Grayscale8).copy())


class MapWorker(QThread):
    """Calcula em quais páginas de saída cada página de origem aparece."""
    done = Signal(object)

    def __init__(self, engine, params, dev):
        super().__init__()
        self.engine, self.params, self.dev = engine, params, dev
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            res = self.engine.page_map(self.params, self.dev, cancel=lambda: self._cancel)
        except Exception:
            res = None
        self.done.emit(None if self._cancel else res)


class OcrThread(QThread):
    """Roda o OCR nas páginas sem texto, em segundo plano, salvando o progresso em disco."""
    progress = Signal(int, int)
    done = Signal(int)
    failed = Signal(str)

    def __init__(self, engine, cache_path):
        super().__init__()
        self.engine, self.cache_path = engine, cache_path
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            n = self.engine.run_ocr(progress=lambda a, b: self.progress.emit(a, b), cancel=lambda: self._cancel,
                                    cache_path=self.cache_path)
            self.done.emit(n)
        except Exception:
            self.failed.emit(traceback.format_exc())


class SuggestDialog(QDialog):
    """Revisão das sugestões. Não bloqueia a janela: ao selecionar um item, ele é mostrado no original."""
    highlight = Signal(object)
    applied = Signal(list)

    def __init__(self, parent, suggestions):
        super().__init__(parent)
        self.setWindowTitle("Cabeçalhos e rodapés encontrados")
        self.setMinimumWidth(520)
        self.suggestions = suggestions
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 16, 16, 16); lay.setSpacing(10)
        t = QLabel("Regiões que se repetem nas páginas"); t.setObjectName("cardTitle")
        sub = QLabel("Marque o que você quer <b>excluir</b>. Ao clicar num item, ele aparece destacado no original. "
                     "Depois você pode desfazer ou ajustar cada exclusão.")
        sub.setWordWrap(True); sub.setObjectName("muted")
        self.lst = QListWidget(); self.lst.setMinimumHeight(180)
        for s in suggestions:
            sample = f"“{s.sample}”" if s.sample else "(sem texto; pode ser só imagem ou filete)"
            it = QListWidgetItem(f"{s.where.capitalize()} · {SCOPES[s.edit.scope]} · {sample}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable); it.setCheckState(Qt.Checked)
            self.lst.addItem(it)
        self.lst.currentRowChanged.connect(self._row)
        row = QHBoxLayout()
        b_all = QPushButton("Marcar todas"); b_none = QPushButton("Desmarcar todas")
        b_all.clicked.connect(lambda: self._set_all(Qt.Checked)); b_none.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        row.addWidget(b_all); row.addWidget(b_none); row.addStretch(1)
        foot = QHBoxLayout(); foot.addStretch(1)
        b_close = QPushButton("Fechar"); b_close.clicked.connect(self.close)
        self.b_apply = QPushButton("Excluir as marcadas"); self.b_apply.setObjectName("primary")
        self.b_apply.clicked.connect(self._apply)
        foot.addWidget(b_close); foot.addWidget(self.b_apply)
        for w in (t, sub, self.lst):
            lay.addWidget(w)
        lay.addLayout(row); lay.addLayout(foot)
        self.lst.setCurrentRow(0)

    def _set_all(self, st):
        for k in range(self.lst.count()):
            self.lst.item(k).setCheckState(st)

    def _row(self, k):
        self.highlight.emit(self.suggestions[k] if 0 <= k < len(self.suggestions) else None)

    def chosen(self):
        return [s.edit for k, s in enumerate(self.suggestions) if self.lst.item(k).checkState() == Qt.Checked]

    def _apply(self):
        self.applied.emit(self.chosen())
        self.close()

    def closeEvent(self, e):
        self.highlight.emit(None)
        super().closeEvent(e)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — PDF legível em qualquer tela")
        self.resize(1480, 900)
        self.setMinimumSize(1120, 700)
        self.setWindowIcon(branding.app_icon())
        self.setAcceptDrops(True)
        self.engine = Engine()
        self.devices = load_devices()
        self.page = 0
        self.out_pages: list = []
        self.out_idx = 0
        self.gen = 0
        self._items: list = []
        self._labels: list = []
        self._pending_sugg: list = []
        self._sd = None
        self._tw = None
        self._mw = None
        self._map_again = False
        self._has_text = True
        self.last_output = None      # último arquivo convertido (para o botão Enviar)
        self.opds = None             # servidor de rede (KOReader)
        self.conn_settings = {"auto_calibre": False}
        self.check_updates = True          # consulta o GitHub ao abrir (desligável na tela Sobre)
        self.update_checked = 0.0
        self.update_skip = ""
        self._update = None
        self._upd_sig = UpdateSignals()
        self._upd_manual = None
        self._ocrt = None
        self._then_convert = False
        self._font = None          # tamanhos em pontos calculados pelo último preview
        self._captions: dict = {}
        self._rows: dict = {}
        self._tips: dict = {}
        self.theme_pref = "auto"
        self.pool = QThreadPool.globalInstance()
        self.sig = Signals()
        self.sig.done.connect(self._on_done)
        self.sig.failed.connect(self._on_failed)
        self.timer = QTimer(self, singleShot=True, interval=140)
        self.timer.timeout.connect(self._run_preview)
        self.map_timer = QTimer(self, singleShot=True, interval=900)
        self.map_timer.timeout.connect(self._start_map)
        self._build()
        self._load_settings()
        QTimer.singleShot(4000, self._auto_check_updates)
        self._apply_preset(self.cb_preset.currentText(), schedule=False)
        self._apply_theme()
        self._update_nav()
        self._edits_changed(save=False)
        self._format_changed(schedule=False)
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self.theme_pref == "auto" and self._apply_theme())
        except Exception:
            pass

    # ------------------------------------------------------------ construção
    @staticmethod
    def _slider(a, b, v):
        s = ClickSlider(Qt.Horizontal); s.setRange(a, b); s.setValue(v); s.setPageStep(max(1, (b - a) // 20)); return s

    def _slider_row(self, form, label, a, b, v, fmt, tip=""):
        s = self._slider(a, b, v); lb = QLabel(fmt(v)); lb.setMinimumWidth(104); lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        s.valueChanged.connect(lambda x: self._refresh_value_labels())
        s.valueChanged.connect(self._schedule)
        self._labels.append((s, lb, fmt))
        row = QHBoxLayout(); row.addWidget(s, 1); row.addWidget(lb)
        cap = QLabel(label); cap.setToolTip(tip); s.setToolTip(tip); s.setAccessibleName(label)
        self._captions[s] = cap; self._rows[s] = lb; self._tips[s] = tip
        form.addRow(cap, row)
        return s

    @staticmethod
    def _pt(x: float) -> str:
        x = round(x * 2) / 2
        return f"{x:g}"

    def _refresh_value_labels(self):
        """Atualiza os rótulos dos controles; tamanho do texto e dos títulos mostram o equivalente em pontos."""
        f = self._font
        for sl, lb, fmt in self._labels:
            txt = fmt(sl.value())
            if f and f.get("size"):
                body = f["body_pt"] * (self.sl_size.value() / 100) / f["size"]
                if sl is self.sl_size:
                    txt += f"  ≈ {self._pt(body)} pt"
                elif sl is self.sl_title and f.get("rel"):
                    rel, bal = f["rel"], self.sl_title.value() / 100
                    eff = rel if rel <= 1.45 else 1.45 + (rel - 1.45) * bal
                    txt += f"  ≈ {self._pt(body * eff)} pt"
            lb.setText(txt)

    def _nav_bar(self, prev_btn, label_widgets, next_btn):
        bar = QHBoxLayout(); bar.setSpacing(8)
        bar.addStretch(1); bar.addWidget(prev_btn)
        for w in label_widgets:
            bar.addWidget(w)
        bar.addWidget(next_btn); bar.addStretch(1)
        return bar

    def _build(self):
        # ---------------- barra lateral
        body = QWidget(); body.setObjectName("sidebarBody")
        lv = QVBoxLayout(body); lv.setContentsMargins(14, 14, 10, 8); lv.setSpacing(12)

        head = QHBoxLayout()
        tcol = QVBoxLayout(); tcol.setSpacing(0)
        title = QLabel(APP_NAME); title.setObjectName("appTitle")
        sub = QLabel("PDF legível em qualquer tela"); sub.setObjectName("muted")
        tcol.addWidget(title); tcol.addWidget(sub)
        logo = QLabel(); logo.setPixmap(branding.logo_pixmap(40)); logo.setFixedSize(40, 40); logo.setAccessibleName("Logo do Legivo")
        head.addWidget(logo); head.addSpacing(8)
        head.addLayout(tcol); head.addStretch(1)
        self.btn_conn = QPushButton(); self.btn_conn.setObjectName("ghost"); self.btn_conn.setFixedSize(36, 36)
        self.btn_conn.setAccessibleName("Conexões"); self.btn_conn.setToolTip("Conexões: Calibre, KOReader por rede e aparelhos por USB")
        self.btn_conn.clicked.connect(self.show_connections)
        head.addWidget(self.btn_conn)
        self.btn_about = QPushButton(); self.btn_about.setObjectName("ghost"); self.btn_about.setFixedSize(36, 36)
        self.btn_about.setAccessibleName("Sobre o Legivo"); self.btn_about.setToolTip("Sobre o Legivo e créditos (F1)")
        self.btn_about.clicked.connect(self.show_about)
        head.addWidget(self.btn_about)
        self.btn_theme = QPushButton(); self.btn_theme.setObjectName("ghost"); self.btn_theme.setFixedSize(36, 36)
        self.btn_theme.setAccessibleName("Tema da interface"); self.btn_theme.setToolTip("Tema: automático, claro ou escuro")
        mt = QMenu(self.btn_theme)
        for label, pref in (("Automático (segue o Windows)", "auto"), ("Claro", "light"), ("Escuro", "dark")):
            mt.addAction(label).triggered.connect(lambda _=False, p=pref: self._set_theme(p))
        self.btn_theme.setMenu(mt)
        head.addWidget(self.btn_theme)
        lv.addLayout(head)

        c1 = Card("Abrir PDF", 1)
        self.btn_open = QPushButton("  Escolher arquivo…"); self.btn_open.setMinimumHeight(36)
        self.btn_open.setToolTip("Abrir um PDF (Ctrl+O). Você também pode arrastar o arquivo para a janela.")
        self.btn_open.clicked.connect(self.open_dialog)
        self.lb_file = QLabel("Nenhum arquivo aberto."); self.lb_file.setObjectName("muted"); self.lb_file.setWordWrap(True)
        c1.body.addWidget(self.btn_open); c1.body.addWidget(self.lb_file)
        lv.addWidget(c1)

        c2 = Card("Para qual tela?", 2)
        f2 = QFormLayout(); f2.setLabelAlignment(Qt.AlignLeft); f2.setVerticalSpacing(8)
        self.cb_dev = QComboBox(); self.cb_dev.setAccessibleName("Dispositivo")
        for d in self.devices:
            if d["id"] == "custom":
                self.cb_dev.insertSeparator(self.cb_dev.count())
            self.cb_dev.addItem(d["nome"], d["id"])
            if d["id"] == "letter":
                self.cb_dev.insertSeparator(self.cb_dev.count())
        self.sp_w = QSpinBox(); self.sp_w.setRange(200, 6000); self.sp_w.setSuffix(" px")
        self.sp_h = QSpinBox(); self.sp_h.setRange(200, 8000); self.sp_h.setSuffix(" px")
        self.sp_dpi = QSpinBox(); self.sp_dpi.setRange(72, 600); self.sp_dpi.setSuffix(" dpi")
        f2.addRow(self.cb_dev)
        self.custom_rows = [(QLabel("Largura"), self.sp_w), (QLabel("Altura"), self.sp_h), (QLabel("Resolução"), self.sp_dpi)]
        for lbl, w in self.custom_rows:
            f2.addRow(lbl, w)
        c2.body.addLayout(f2)
        lv.addWidget(c2)

        c3 = Card("Que tipo de documento?", 3)
        self.cb_preset = QComboBox(); self.cb_preset.addItems(list(PRESETS)); self.cb_preset.setAccessibleName("Tipo de documento")
        self.lb_preset = QLabel(); self.lb_preset.setObjectName("muted"); self.lb_preset.setWordWrap(True)
        c3.body.addWidget(self.cb_preset); c3.body.addWidget(self.lb_preset)
        lv.addWidget(c3)

        c4 = Card("Formato de saída", 4)
        self.cb_fmt = QComboBox(); self.cb_fmt.setAccessibleName("Formato de saída")
        self.cb_fmt.addItem("PDF para tela (layout refeito)", "pdf"); self.cb_fmt.addItem("EPUB (texto reorganizado)", "epub")
        self.lb_fmt = QLabel(); self.lb_fmt.setObjectName("muted"); self.lb_fmt.setWordWrap(True)
        self.cb_color = QComboBox(); self.cb_color.setAccessibleName("Cores do PDF")
        self.cb_color.addItem("Tons de cinza (leitor e-ink, arquivo menor)", "gray")
        self.cb_color.addItem("Colorido (imprimir ou tela colorida)", "color")
        self.cb_color.setToolTip("Colorido mantém as cores das figuras e do texto do original; o arquivo fica maior.")
        c4.body.addWidget(self.cb_fmt); c4.body.addWidget(self.lb_fmt); c4.body.addWidget(self.cb_color)
        lv.addWidget(c4)

        c4 = Card("Ajuste fino", 5)
        f4 = QFormLayout(); f4.setVerticalSpacing(6); f4.setLabelAlignment(Qt.AlignLeft)
        self.sl_size = self._slider_row(f4, "Tamanho do texto", 50, 400, 100, lambda v: f"{v}%",
                                        "100% faz a coluna ocupar a largura da tela. Maior = letras maiores. No EPUB, só muda a prévia.")
        self.sl_title = self._slider_row(f4, "Tamanho dos títulos", 0, 100, 35, lambda v: f"{v}%",
                                         "Quanto menor, mais os títulos se aproximam do tamanho do texto. 100% mantém a proporção do original.")
        self.sl_margin = self._slider_row(f4, "Margem da página", 0, 15, 2, lambda v: f"{v} mm")
        self.sl_lead = self._slider_row(f4, "Espaço entre linhas", 0, 60, 12, lambda v: f"{v / 100:.2f}".replace(".", ","))
        self.sl_con = self._slider_row(f4, "Contraste", 80, 250, 100, lambda v: f"{v}%")
        self.lb_epub_note = QLabel("No EPUB, o aparelho controla letra, margem e contraste. Os controles em cinza não se aplicam; "
                                   "aqui só dá para ajustar o tamanho da letra da prévia.")
        self.lb_epub_note.setObjectName("hint"); self.lb_epub_note.setWordWrap(True); self.lb_epub_note.setVisible(False)
        c4.body.addWidget(self.lb_epub_note)
        c4.body.addLayout(f4)
        self.ck_wrap = QCheckBox("Reorganizar o texto (refazer as quebras de linha)")
        self.ck_just = QCheckBox("Justificar parágrafos")
        self.ck_rot = QCheckBox("Girar figuras grandes e largas")
        self.ck_inv = QCheckBox("Inverter cores (fundo preto)")
        for c in (self.ck_wrap, self.ck_just, self.ck_rot, self.ck_inv):
            c4.body.addWidget(c)
        self.adv = Collapsible("Avançado: colunas e cortes")
        fa = QFormLayout(); fa.setVerticalSpacing(8)
        self.cb_cols = QComboBox(); self.cb_cols.addItem("1 (sem colunas)", 1); self.cb_cols.addItem("até 2", 2); self.cb_cols.addItem("até 4", 4)
        self.sp_thr = QSpinBox(); self.sp_thr.setRange(60, 250)
        self.sp_gap = QDoubleSpinBox(); self.sp_gap.setRange(0.5, 15); self.sp_gap.setSingleStep(0.5); self.sp_gap.setSuffix(" mm")
        self.sp_ct, self.sp_cb, self.sp_cl, self.sp_cr = (QDoubleSpinBox() for _ in range(4))
        for s in (self.sp_ct, self.sp_cb, self.sp_cl, self.sp_cr):
            s.setRange(0, 80); s.setSuffix(" mm"); s.setSingleStep(1)
        self.ck_fig = QCheckBox("Detectar figuras")
        fa.addRow("Colunas", self.cb_cols); fa.addRow("Sensibilidade da tinta", self.sp_thr)
        fa.addRow("Espaço entre colunas", self.sp_gap)
        fa.addRow("Ignorar no topo", self.sp_ct); fa.addRow("Ignorar embaixo", self.sp_cb)
        fa.addRow("Ignorar à esquerda", self.sp_cl); fa.addRow("Ignorar à direita", self.sp_cr)
        fa.addRow(self.ck_fig)
        self.adv.body_lay.addLayout(fa)
        c4.body.addWidget(self.adv)
        lv.addWidget(c4)
        self._pdf_only = [self.sl_title, self.sl_margin, self.sl_lead, self.sl_con, self.ck_wrap, self.ck_just, self.ck_rot, self.ck_inv, self.cb_color]
        for c in (self.ck_wrap, self.ck_just, self.ck_rot, self.ck_inv, self.cb_color):
            self._tips[c] = c.toolTip()

        c5 = Card("Edições manuais")
        self.btn_suggest = QPushButton("  Sugerir cabeçalhos e rodapés…")
        self.btn_suggest.setToolTip("Procura cabeçalhos, rodapés e números de página que se repetem e sugere excluí-los.")
        self.btn_suggest.clicked.connect(lambda: self._start_suggest(auto=False))
        self.btn_doubts = QPushButton("  Revisar dúvidas do programa…")
        self.btn_doubts.setToolTip("O programa pergunta nos pontos em que não tem certeza (é tabela? é imagem?). Respostas parecidas são aplicadas de uma vez.")
        self.btn_doubts.clicked.connect(self.show_doubts)
        self.lst_edits = QListWidget(); self.lst_edits.setMaximumHeight(130)
        self.lst_edits.setToolTip("Suas edições. Selecione uma para vê-la no original; Delete a remove.")
        self.lst_edits.currentRowChanged.connect(self._list_selected)
        self.lb_edits_empty = QLabel("Nenhuma edição ainda. Desenhe sobre o original ou clique com o botão direito numa região.")
        self.lb_edits_empty.setObjectName("muted"); self.lb_edits_empty.setWordWrap(True)
        row5 = QHBoxLayout()
        self.btn_rm = QPushButton("  Remover"); self.btn_rm.clicked.connect(lambda: self._remove_edit(self.lst_edits.currentRow()))
        self.btn_clear = QPushButton("Limpar tudo"); self.btn_clear.clicked.connect(self.clear_edits)
        row5.addWidget(self.btn_rm); row5.addWidget(self.btn_clear)
        c5.body.addWidget(self.btn_suggest); c5.body.addWidget(self.btn_doubts); c5.body.addWidget(self.lb_edits_empty); c5.body.addWidget(self.lst_edits); c5.body.addLayout(row5)
        lv.addWidget(c5)
        lv.addStretch(1)

        scroll = QScrollArea(); scroll.setWidget(body); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        foot = QFrame(); foot.setObjectName("card")
        fl = QVBoxLayout(foot); fl.setContentsMargins(14, 12, 14, 12); fl.setSpacing(8)
        self.btn_conv = QPushButton("  Converter e salvar…"); self.btn_conv.setObjectName("primary"); self.btn_conv.setMinimumHeight(42)
        self.btn_conv.setToolTip("Converte o documento inteiro (Ctrl+S)")
        self.btn_conv.clicked.connect(self.convert_dialog)
        self.btn_send = QPushButton("  Enviar ou abrir com…"); self.btn_send.setEnabled(False)
        self.btn_send.setToolTip("Calibre, Kindle, Kobo ou KOReader. Fica disponível depois de converter.")
        self.btn_send.clicked.connect(self.show_send)
        self.pb = QProgressBar(); self.pb.setVisible(False)
        self.btn_cancel = QPushButton("Cancelar"); self.btn_cancel.setVisible(False)
        fl.addWidget(self.btn_conv); fl.addWidget(self.btn_send); fl.addWidget(self.pb); fl.addWidget(self.btn_cancel)
        side = QWidget(); sl = QVBoxLayout(side); sl.setContentsMargins(0, 0, 0, 12); sl.setSpacing(8)
        sl.addWidget(scroll, 1)
        fw = QWidget(); fwl = QVBoxLayout(fw); fwl.setContentsMargins(14, 0, 10, 0); fwl.addWidget(foot)
        sl.addWidget(fw)
        side.setMinimumWidth(390); side.setMaximumWidth(440)

        # ---------------- área de trabalho
        right = QWidget(); right.setObjectName("root")
        rv = QVBoxLayout(right); rv.setContentsMargins(6, 14, 14, 8); rv.setSpacing(10)

        tb = QFrame(); tb.setObjectName("toolbar")
        tl = QVBoxLayout(tb); tl.setContentsMargins(12, 10, 12, 10); tl.setSpacing(8)
        tools = QHBoxLayout(); tools.setSpacing(0)
        self.tool_group = QButtonGroup(self)
        self.tool_buttons = []
        specs = (("  Selecionar", "cursor", "first", "Clique numa edição para selecioná-la; arraste para mover e use as alças para redimensionar."),
                 ("  Excluir área", "exclude", "mid", "Arraste sobre o original para ignorar uma região (cabeçalho, número de página, rodapé, marca d’água…)."),
                 ("  Manter como figura", "image", "last", "Arraste sobre o original para tratar a região como uma imagem inteira (sem reorganizar o texto)."))
        for i, (txt, ic, seg, tip) in enumerate(specs):
            b = QPushButton(txt); b.setCheckable(True); b.setToolTip(tip); b.setMinimumHeight(34)
            b.setProperty("seg", seg); b.setAccessibleName(txt.strip())
            self.tool_group.addButton(b, i); tools.addWidget(b); self.tool_buttons.append((b, ic))
            if i == 0:
                b.setChecked(True)
        tools.addSpacing(16)
        al = QLabel("Aplicar em"); al.setObjectName("muted"); tools.addWidget(al); tools.addSpacing(6)
        self.cb_scope = QComboBox(); self.cb_scope.setAccessibleName("Onde aplicar a edição")
        for k, t in (("page", "Só esta página"), ("all", "Todas as páginas"), ("odd", "Páginas ímpares"), ("even", "Páginas pares")):
            self.cb_scope.addItem(t, k)
        self.cb_scope.setToolTip("Onde a nova edição será aplicada.")
        tools.addWidget(self.cb_scope); tools.addSpacing(10)
        self.btn_undo = QPushButton("  Desfazer"); self.btn_undo.setToolTip("Desfaz a última edição (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.undo_edit)
        tools.addWidget(self.btn_undo); tools.addSpacing(10)
        self.btn_overlay = QPushButton("  Sobrepor páginas…")
        self.btn_overlay.setToolTip("Empilha várias páginas com transparência para achar o que se repete (cabeçalhos, rodapés) e excluir de uma vez.")
        self.btn_overlay.clicked.connect(self.show_overlay)
        tools.addWidget(self.btn_overlay); tools.addStretch(1)
        tl.addLayout(tools)
        self.tool_group.idToggled.connect(lambda i, on: on and self.view_orig.set_drawing(i > 0))
        leg = QHBoxLayout(); self.legend = LegendBar(); leg.addWidget(self.legend, 1)
        tl.addLayout(leg)
        self.legend.setToolTip("Dica: clique com o botão direito do mouse numa região detectada para excluí-la ou marcá-la como figura.")
        rv.addWidget(tb)

        self.infobar = InfoBar()
        self.infobar.action.connect(self._review_suggestions)
        rv.addWidget(self.infobar)
        self.updbar = InfoBar(); self.updbar.action.connect(self._open_update)
        self.updbar.dismissed.connect(self._skip_update)
        rv.addWidget(self.updbar)
        self.ocrbar = InfoBar(); self.ocrbar.action.connect(self._ocr_prompt)
        self.ocrbar.dismissed.connect(lambda: None)
        rv.addWidget(self.ocrbar)

        work = QHBoxLayout(); work.setSpacing(12)

        # painel de miniaturas (retrátil)
        self.thumb_panel = QFrame(); self.thumb_panel.setObjectName("card"); self.thumb_panel.setFixedWidth(150)
        tpl = QVBoxLayout(self.thumb_panel); tpl.setContentsMargins(8, 10, 8, 8); tpl.setSpacing(6)
        tt = QLabel("Páginas"); tt.setObjectName("cardTitle"); tpl.addWidget(tt)
        self.lst_thumbs = QListWidget(); self.lst_thumbs.setObjectName("thumbs")
        self.lst_thumbs.setViewMode(QListView.IconMode); self.lst_thumbs.setFlow(QListView.TopToBottom)
        self.lst_thumbs.setWrapping(False); self.lst_thumbs.setMovement(QListView.Static)
        self.lst_thumbs.setResizeMode(QListView.Adjust); self.lst_thumbs.setIconSize(QSize(96, 128))
        self.lst_thumbs.setGridSize(QSize(122, 178)); self.lst_thumbs.setSpacing(2)
        self.lst_thumbs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lst_thumbs.setAccessibleName("Miniaturas das páginas")
        self.lst_thumbs.currentRowChanged.connect(lambda r: r >= 0 and self.sp_page.setValue(r + 1))
        self.lb_map = QLabel(""); self.lb_map.setObjectName("muted"); self.lb_map.setWordWrap(True)
        tpl.addWidget(self.lst_thumbs, 1); tpl.addWidget(self.lb_map)
        work.addWidget(self.thumb_panel)

        p1 = QVBoxLayout(); p1.setSpacing(6)
        h1 = QHBoxLayout()
        self.btn_thumbs = QPushButton("  Páginas"); self.btn_thumbs.setCheckable(True); self.btn_thumbs.setChecked(True)
        self.btn_thumbs.setToolTip("Mostrar ou esconder a coluna de miniaturas"); self.btn_thumbs.setAccessibleName("Mostrar miniaturas")
        self.btn_thumbs.toggled.connect(self.thumb_panel.setVisible)
        t1 = QLabel("Original"); t1.setObjectName("paneTitle")
        self.ck_over = QCheckBox("Mostrar o que o Legivo detectou"); self.ck_over.setChecked(True)
        self.ck_over.toggled.connect(lambda _: self._refresh_overlay())
        h1.addWidget(self.btn_thumbs); h1.addSpacing(6); h1.addWidget(t1); h1.addStretch(1); h1.addWidget(self.ck_over)
        p1.addLayout(h1)
        self.stack = QStackedWidget()
        self.empty = EmptyState(); self.empty.open_requested.connect(self.open_dialog)
        self.view_orig = OriginalView("")
        self.stack.addWidget(self.empty); self.stack.addWidget(self.view_orig)
        p1.addWidget(self.stack, 1)
        self.btn_prev = QPushButton(); self.btn_next = QPushButton()
        for b, nm, tip in ((self.btn_prev, "Página anterior", "Página anterior (Page Up)"), (self.btn_next, "Próxima página", "Próxima página (Page Down)")):
            b.setFixedSize(36, 36); b.setAccessibleName(nm); b.setToolTip(tip)
        self.sp_page = QSpinBox(); self.sp_page.setMinimum(1); self.sp_page.setMinimumWidth(72); self.sp_page.setAlignment(Qt.AlignCenter)
        self.sp_page.setAccessibleName("Página do original")
        self.lb_total = QLabel("de 0"); self.lb_total.setObjectName("muted")
        self.btn_prev.clicked.connect(lambda: self.sp_page.setValue(self.sp_page.value() - 1))
        self.btn_next.clicked.connect(lambda: self.sp_page.setValue(self.sp_page.value() + 1))
        self.sp_page.valueChanged.connect(self._page_changed)
        pl = QLabel("Página"); pl.setObjectName("muted")
        p1.addLayout(self._nav_bar(self.btn_prev, (pl, self.sp_page, self.lb_total), self.btn_next))
        self.view_orig.region_drawn.connect(self._region_drawn)
        self.view_orig.edit_changed.connect(self._edit_moved)
        self.view_orig.edit_selected.connect(self._view_selected)
        self.view_orig.delete_requested.connect(self._remove_edit)
        self.view_orig.context_requested.connect(self._show_context)
        self.legend.kinds_changed.connect(self.view_orig.set_visible_kinds)
        self.view_orig.set_visible_kinds(self.legend.visible_kinds())

        p2 = QVBoxLayout(); p2.setSpacing(6)
        h2 = QHBoxLayout()
        t2 = QLabel("Resultado na tela"); t2.setObjectName("paneTitle"); h2.addWidget(t2); h2.addStretch(1)
        p2.addLayout(h2)
        t2.setMinimumHeight(self.btn_thumbs.sizeHint().height())     # alinha o painel com o do original
        self.view_out = FitLabel("O resultado aparece aqui depois que você abrir um PDF.")
        p2.addWidget(self.view_out, 1)
        self.btn_op = QPushButton(); self.btn_on = QPushButton(); self.lb_out = QLabel("—"); self.lb_out.setObjectName("muted")
        for b, nm in ((self.btn_op, "Página de saída anterior"), (self.btn_on, "Próxima página de saída")):
            b.setFixedSize(36, 36); b.setAccessibleName(nm); b.setToolTip(nm)
        self.btn_op.clicked.connect(lambda: self._out_step(-1)); self.btn_on.clicked.connect(lambda: self._out_step(1))
        ol = QLabel("Saída"); ol.setObjectName("muted")
        p2.addLayout(self._nav_bar(self.btn_op, (ol, self.lb_out), self.btn_on))
        work.addLayout(p1, 1); work.addLayout(p2, 1)
        rv.addLayout(work, 1)

        self.status = QLabel(""); self.status.setObjectName("status"); self.status.setContentsMargins(10, 2, 10, 8)
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().setSizeGripEnabled(False)

        split = QSplitter(); split.addWidget(side); split.addWidget(right); split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(False)
        self.setCentralWidget(split)

        self.cb_dev.currentIndexChanged.connect(self._device_changed)
        self.cb_preset.currentTextChanged.connect(lambda t: self._apply_preset(t))
        self.cb_fmt.currentIndexChanged.connect(lambda _: self._format_changed())
        for w in (self.ck_wrap, self.ck_just, self.ck_rot, self.ck_inv, self.ck_fig):
            w.toggled.connect(self._schedule)
        self.cb_color.currentIndexChanged.connect(self._schedule)
        for w in (self.sp_w, self.sp_h, self.sp_dpi, self.sp_thr, self.sp_gap, self.sp_ct, self.sp_cb, self.sp_cl, self.sp_cr):
            w.valueChanged.connect(self._schedule)
        self.cb_cols.currentIndexChanged.connect(self._schedule)

        for text, keys, slot in (("Desfazer", QKeySequence.Undo, self.undo_edit), ("Abrir…", QKeySequence.Open, self.open_dialog),
                                 ("Converter", QKeySequence.Save, self.convert_dialog),
                                 ("Sobre", QKeySequence(Qt.Key_F1), self.show_about),
                                 ("Página anterior", QKeySequence(Qt.Key_PageUp), lambda: self.sp_page.setValue(self.sp_page.value() - 1)),
                                 ("Próxima página", QKeySequence(Qt.Key_PageDown), lambda: self.sp_page.setValue(self.sp_page.value() + 1))):
            a = QAction(text, self); a.setShortcut(keys); a.triggered.connect(slot); self.addAction(a)

    # ------------------------------------------------------------ tema e ícones
    def _set_theme(self, pref: str):
        self.theme_pref = pref
        self._apply_theme()

    def _apply_theme(self):
        theme.apply_theme(QApplication.instance(), self.theme_pref)
        self._refresh_icons()
        self.lb_preset.setText(PRESET_HELP.get(self.cb_preset.currentText(), ""))

    def _refresh_icons(self):
        t = theme.tokens()
        txt, mut, pri = t["text"], t["muted"], t["primary"]
        self.btn_open.setIcon(icons.icon("folder", txt, 18))
        self.btn_about.setIcon(icons.icon("info", txt, 20))
        self.btn_conn.setIcon(icons.icon("link", txt, 20))
        self.btn_send.setIcon(icons.icon("save", txt, 18))
        self.btn_conv.setIcon(icons.icon("save", t["on_primary"], 20))
        self.btn_suggest.setIcon(icons.icon("sparkle", pri, 18))
        self.btn_doubts.setIcon(icons.icon("info", pri, 18))
        self.btn_rm.setIcon(icons.icon("trash", txt, 16))
        self.btn_undo.setIcon(icon2("undo", txt, txt, 18))
        self.btn_overlay.setIcon(icons.icon("grid", txt, 18))
        self.btn_thumbs.setIcon(icon2("grid", txt, pri, 18))
        for b, d in ((self.btn_prev, "left"), (self.btn_op, "left")):
            b.setIcon(icons.icon("chevron_left", txt, 18))
        for b in (self.btn_next, self.btn_on):
            b.setIcon(icons.icon("chevron_right", txt, 18))
        for b, name in self.tool_buttons:
            b.setIcon(icon2(name, txt, pri, 18))
        self.btn_theme.setIcon(icons.icon("moon" if theme.mode() == "light" else "sun", txt, 20))
        self.adv.refresh_icons(); self.infobar.refresh_icons(); self.ocrbar.refresh_icons(); self.empty.refresh_icons()

    # ------------------------------------------------------------ parâmetros
    def _fmt(self) -> str:
        return self.cb_fmt.currentData() or "pdf"

    def _device(self) -> dict:
        did = self.cb_dev.currentData()
        d = dict(next((x for x in self.devices if x["id"] == did), self.devices[0]))
        if d["id"] == "custom":
            d.update(width=self.sp_w.value(), height=self.sp_h.value(), dpi=self.sp_dpi.value())
        return d

    def _params(self) -> Params:
        p = preset(self.cb_preset.currentText())
        p.size = self.sl_size.value() / 100
        p.title_balance = self.sl_title.value() / 100
        p.margin_mm = float(self.sl_margin.value())
        p.leading = self.sl_lead.value() / 100
        p.contrast = self.sl_con.value() / 100
        p.wrap, p.justify = self.ck_wrap.isChecked(), self.ck_just.isChecked()
        p.rotate_figures, p.invert = self.ck_rot.isChecked(), self.ck_inv.isChecked()
        p.color = self.cb_color.currentData() == "color"
        p.detect_figures = self.ck_fig.isChecked()
        p.max_cols = self.cb_cols.currentData()
        p.threshold, p.col_gap_mm = self.sp_thr.value(), self.sp_gap.value()
        p.crop_top_mm, p.crop_bottom_mm = self.sp_ct.value(), self.sp_cb.value()
        p.crop_left_mm, p.crop_right_mm = self.sp_cl.value(), self.sp_cr.value()
        return p

    def _apply_preset(self, name: str, schedule=True):
        p = preset(name)
        widgets = [self.sl_size, self.sl_title, self.sl_margin, self.sl_lead, self.sl_con, self.ck_wrap, self.ck_just, self.ck_rot,
                   self.ck_inv, self.ck_fig, self.cb_cols, self.sp_thr, self.sp_gap, self.sp_ct, self.sp_cb, self.sp_cl, self.sp_cr]
        for w in widgets:
            w.blockSignals(True)
        self.sl_size.setValue(round(p.size * 100)); self.sl_title.setValue(round(p.title_balance * 100))
        self.sl_margin.setValue(round(p.margin_mm)); self.sl_lead.setValue(round(p.leading * 100))
        self.sl_con.setValue(round(p.contrast * 100))
        self.ck_wrap.setChecked(p.wrap); self.ck_just.setChecked(p.justify); self.ck_rot.setChecked(p.rotate_figures)
        self.ck_inv.setChecked(p.invert); self.ck_fig.setChecked(p.detect_figures)
        self.cb_cols.setCurrentIndex(max(0, self.cb_cols.findData(p.max_cols)))
        self.sp_thr.setValue(p.threshold); self.sp_gap.setValue(p.col_gap_mm)
        self.sp_ct.setValue(p.crop_top_mm); self.sp_cb.setValue(p.crop_bottom_mm)
        self.sp_cl.setValue(p.crop_left_mm); self.sp_cr.setValue(p.crop_right_mm)
        for w in widgets:
            w.blockSignals(False)
        self._refresh_value_labels()
        self.lb_preset.setText(PRESET_HELP.get(name, ""))
        if schedule:
            self._schedule()

    def _device_changed(self):
        d = self._device()
        custom = d["id"] == "custom"
        for lbl, w in self.custom_rows:
            lbl.setVisible(custom); w.setVisible(custom)
        if not custom:
            for sp, k in ((self.sp_w, "width"), (self.sp_h, "height"), (self.sp_dpi, "dpi")):
                sp.blockSignals(True); sp.setValue(d[k]); sp.blockSignals(False)
        self._schedule()

    def _format_changed(self, schedule=True):
        epub = self._fmt() == "epub"
        why = "Não se aplica ao EPUB: o aparelho controla isso."
        for w in self._pdf_only:
            w.setEnabled(not epub)
            tip = why if epub else self._tips.get(w, "")
            w.setToolTip(tip)
            if w in self._captions:
                self._captions[w].setEnabled(not epub); self._captions[w].setToolTip(tip); self._rows[w].setEnabled(not epub)
        self._captions[self.sl_size].setText("Letra da prévia" if epub else "Tamanho do texto")
        self.lb_epub_note.setVisible(epub)
        msg = FORMAT_HELP[self._fmt()]
        if epub and self.engine.n and not self._has_text:
            msg += "\n⚠ Este PDF é só imagem: ao converter, o Legivo oferece o OCR para reconhecer o texto."
        self.lb_fmt.setText(msg)
        self._font = None
        self._refresh_value_labels()
        self._reset_map_labels()
        if schedule:
            self._schedule()

    # ------------------------------------------------------------ arquivos
    def open_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", str(Path(self.engine.path).parent) if self.engine.path else "", "PDF (*.pdf)")
        if f:
            self.open_file(f)

    def open_file(self, path: str):
        self._stop_workers()
        try:
            self.engine.open(path)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Não consegui abrir o arquivo:\n{e}")
            return
        self.lb_file.setText(f"<b>{Path(path).name}</b><br>{self.engine.n} páginas")
        self.sp_page.blockSignals(True)
        self.sp_page.setRange(1, max(1, self.engine.n)); self.sp_page.setValue(1)
        self.sp_page.blockSignals(False)
        self.lb_total.setText(f"de {self.engine.n}")
        self.page = 0
        self.stack.setCurrentIndex(1)
        self.infobar.setVisible(False)
        self.ocrbar.setVisible(False)
        try:
            pf = self._project_file()
            if pf.exists():
                self.engine.load_edits(pf)
            if self._ocr_cache_file().exists():
                self.engine.load_ocr(self._ocr_cache_file())
        except Exception as ex:
            self._soft_error("Não consegui carregar as edições ou o OCR salvos deste PDF", ex)
        try:
            self._has_text = has_text(self.engine)
        except Exception:
            self._has_text = True
        self._build_thumbs()
        self._update_nav()
        self._format_changed(schedule=False)
        self._edits_changed(save=False)
        if not self.engine.edits and self._has_text:
            self._start_suggest(auto=True)
        self._check_ocr_need()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".pdf") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.toLocalFile().lower().endswith(".pdf"):
                self.open_file(u.toLocalFile()); break

    # ------------------------------------------------------------ OCR
    def _ocr_cache_file(self) -> Path:
        p = Path(self.engine.path)
        return settings_path().parent / "legivo_projetos" / f"{p.stem}-{p.stat().st_size}.ocr.json"

    def _check_ocr_need(self):
        """PDF só de imagem: oferece o OCR (sem rodar nada sozinho)."""
        if self._has_text or not self.engine.n:
            return
        ok, why = ocrmod.available()
        mins = max(1, round(self.engine.n * ocrmod.SECONDS_PER_PAGE / 60))
        if ok:
            self.ocrbar.show_message(
                f"Este PDF é só imagem (sem texto). Reconhecer o texto (OCR) permite gerar EPUB e reorganizar o texto "
                f"de verdade. Leva cerca de {mins} min para {self.engine.n} página(s), em segundo plano.", "Reconhecer texto…")
        else:
            self.ocrbar.show_message("Este PDF é só imagem, e o OCR não está disponível nesta instalação.", "Entendi")

    def _ocr_prompt(self, then_convert=False):
        ok, why = ocrmod.available()
        if not ok:
            QMessageBox.information(self, APP_NAME, f"O OCR não está disponível nesta instalação.\n{why}")
            return
        mins = max(1, round(self.engine.n * ocrmod.SECONDS_PER_PAGE / 60))
        r = QMessageBox.question(
            self, APP_NAME, f"O OCR vai analisar as páginas sem texto ({self.engine.n} no total, cerca de {mins} min). "
            "Ele roda em segundo plano, o resultado fica salvo e você pode cancelar quando quiser.\n\nContinuar?")
        if r == QMessageBox.Yes:
            self._start_ocr(then_convert=bool(then_convert))

    def _start_ocr(self, then_convert=False):
        self._then_convert = then_convert
        self.btn_conv.setEnabled(False); self.pb.setVisible(True); self.pb.setValue(0); self.btn_cancel.setVisible(True)
        self.status.setText("Reconhecendo o texto (OCR)…")
        self._ocrt = OcrThread(self.engine, self._ocr_cache_file())
        self._ocrt.progress.connect(lambda a, b: (self.pb.setMaximum(b), self.pb.setValue(a),
                                                  self.status.setText(f"Reconhecendo o texto (OCR)… página {a} de {b}")))
        self._ocrt.done.connect(self._ocr_done)
        self._ocrt.failed.connect(self._ocr_failed)
        try:
            self.btn_cancel.clicked.disconnect()
        except Exception:
            pass
        self.btn_cancel.clicked.connect(self._ocrt.cancel)
        self._ocrt.start()

    def _soft_error(self, msg: str, ex: Exception):
        """Falha que não impede o uso, mas que o usuário precisa saber (antes era engolida em silêncio)."""
        log.warning("%s: %r", msg, ex)
        self.status.setText(f"{msg}: {ex}")

    def _ocr_end(self):
        self.pb.setVisible(False); self.btn_cancel.setVisible(False); self.btn_conv.setEnabled(self.engine.n > 0)
        try:
            self.btn_cancel.clicked.disconnect()
        except Exception:
            pass

    def _ocr_done(self, n):
        cancelled = self._ocrt is not None and self._ocrt._cancel
        self._ocr_end()
        self._has_text = has_text(self.engine)
        self.ocrbar.setVisible(False)
        self._format_changed(schedule=True)
        if cancelled:
            self.status.setText("OCR cancelado. O que já foi reconhecido ficou salvo.")
            return
        self.status.setText(f"OCR concluído: {n} página(s) reconhecida(s).")
        if self._then_convert:
            self._then_convert = False
            self.convert_dialog()

    def _ocr_failed(self, tb):
        self._ocr_end()
        QMessageBox.critical(self, APP_NAME, "Erro no OCR:\n" + tb[-700:])

    # ------------------------------------------------------------ sobre e envio
    def show_about(self):
        AboutDialog(self).exec()

    # -- aviso de nova versão
    def _auto_check_updates(self):
        """Ao abrir: no máximo uma consulta por dia, e só se o usuário não desligou."""
        if self.check_updates and time.time() - self.update_checked > 24 * 3600:
            self._start_update_check(manual=None)

    def _start_update_check(self, manual=None):
        self._upd_manual = manual
        self._upd_sig = UpdateSignals()
        self._upd_sig.found.connect(self._update_found)
        self.pool.start(UpdateJob(self._upd_sig))

    def check_updates_now(self, parent_dialog):
        self._start_update_check(manual=parent_dialog)

    def _update_found(self, up):
        self.update_checked = time.time()
        manual = self._upd_manual
        self._upd_manual = None
        if up is not None:
            self._update = up
            if manual is not None or up.version != self.update_skip:
                self.updbar.show_message(f"Há uma versão nova do Legivo: {up.version} (você usa a {__version__}).", "Ver e baixar")
            if manual is not None:
                QMessageBox.information(manual, APP_NAME, f"Há uma versão nova: {up.version}. Use o botão \"Ver e baixar\" no topo da janela.")
        elif manual is not None:
            QMessageBox.information(manual, APP_NAME, "Você já usa a versão mais recente (ou não foi possível consultar o GitHub agora).")

    def _open_update(self):
        webbrowser.open(self._update.url if self._update else updates.PAGE_RELEASES)

    def _skip_update(self):
        if self._update:
            self.update_skip = self._update.version        # não insiste na mesma versão

    def _get_opds(self):
        return self.opds

    def _set_opds(self, srv):
        if self.opds is not None and srv is None:
            self.opds.stop()
        self.opds = srv

    def show_connections(self):
        ConnectionsDialog(self, self.conn_settings, self._get_opds, self._set_opds, self.last_output).exec()

    def show_overlay(self):
        if not self.engine.n:
            return

        def add(kind, rect, scope):
            if kind == "undo":
                self.undo_edit()
            else:
                self.engine.add_edit(Edit(kind, *rect, scope=scope, page=-1))
                self._edits_changed()
        OverlayDialog(self, self.engine, self.page, add).exec()

    def show_doubts(self):
        if not self.engine.n:
            return

        def apply(edits):
            for e in edits:
                self.engine.add_edit(e)
            self._edits_changed()
        cpath = self._project_file().with_suffix(".duvidas.json")
        DoubtsDialog(self, self.engine, self._params(), cpath, apply).exec()

    def show_send(self):
        if self.last_output and Path(self.last_output).exists():
            SendDialog(self, self.last_output).exec()

    # ------------------------------------------------------------ miniaturas e mapa de páginas
    def _stop_workers(self):
        if self._ocrt is not None:
            self._ocrt.cancel(); self._ocrt.wait(5000); self._ocrt = None
        if self._tw is not None:
            self._tw.stop(); self._tw.wait(2000); self._tw = None
        if self._mw is not None:
            self._mw.cancel(); self._mw.wait(2000); self._mw = None
        self._map_again = False

    def _build_thumbs(self):
        self.lst_thumbs.blockSignals(True)
        self.lst_thumbs.clear()
        ph = QPixmap(96, 128); ph.fill(QColor("#FFFFFF"))
        for i in range(self.engine.n):
            it = QListWidgetItem(QIcon(ph), str(i + 1)); it.setTextAlignment(Qt.AlignHCenter)
            self.lst_thumbs.addItem(it)
        self.lst_thumbs.setCurrentRow(0)
        self.lst_thumbs.blockSignals(False)
        self._tw = ThumbWorker(self.engine, self.engine.n)
        self._tw.thumb.connect(self._on_thumb)
        self._tw.start()
        self._reset_map_labels()

    def _on_thumb(self, i, img):
        if i < self.lst_thumbs.count():
            pm = QPixmap.fromImage(img).scaled(96, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lst_thumbs.item(i).setIcon(QIcon(pm))

    def _sync_thumbs(self):
        if 0 <= self.page < self.lst_thumbs.count() and self.lst_thumbs.currentRow() != self.page:
            self.lst_thumbs.blockSignals(True)
            self.lst_thumbs.setCurrentRow(self.page)
            self.lst_thumbs.blockSignals(False)
            self.lst_thumbs.scrollToItem(self.lst_thumbs.item(self.page))

    def _reset_map_labels(self):
        for i in range(self.lst_thumbs.count()):
            self.lst_thumbs.item(i).setText(str(i + 1))
        if self._fmt() == "epub":
            self.lb_map.setText("No EPUB o aparelho decide a paginação.")
        elif self.engine.n > MAX_MAP_PAGES:
            self.lb_map.setText("Documento grande: a contagem de páginas de saída aparece só na conversão.")
        else:
            self.lb_map.setText("")

    def _start_map(self):
        if not self.engine.n or self._fmt() == "epub" or self.engine.n > MAX_MAP_PAGES:
            return
        if self._mw is not None and self._mw.isRunning():
            self._mw.cancel(); self._map_again = True
            return
        self._mw = MapWorker(self.engine, self._params(), self._device())
        self._mw.done.connect(self._map_done)
        self._mw.finished.connect(self._map_finished)
        self.lb_map.setText("Calculando as páginas de saída…")
        self._mw.start()

    def _map_finished(self):
        if self._map_again:
            self._map_again = False
            self._start_map()

    def _map_done(self, res):
        if not res or self._fmt() == "epub":
            return
        rows, total = res
        for i, (a, b) in enumerate(rows):
            if i < self.lst_thumbs.count():
                self.lst_thumbs.item(i).setText(f"{i + 1}\n→ {a}" if a == b else f"{i + 1}\n→ {a}–{b}")
        self.lb_map.setText(f"{len(rows)} páginas viram {total} de saída.")

    # ------------------------------------------------------------ edições manuais
    def _project_file(self) -> Path:
        p = Path(self.engine.path)
        return settings_path().parent / "legivo_projetos" / f"{p.stem}-{p.stat().st_size}.json"

    def _add_edit(self, kind, rect, scope, select=True):
        x0, y0, x1, y1 = (max(0.0, min(1.0, v)) for v in rect)
        if not self.engine.n or (x1 - x0) < 0.004 or (y1 - y0) < 0.004:
            return
        self.engine.add_edit(Edit(kind, x0, y0, x1, y1, scope, self.page if scope == "page" else -1))
        self._edits_changed()
        if select:
            self.lst_edits.setCurrentRow(len(self.engine.edits) - 1)

    def _region_drawn(self, x0, y0, x1, y1):
        kind = {1: "exclude", 2: "figure"}.get(self.tool_group.checkedId())
        if kind:
            self._add_edit(kind, (x0, y0, x1, y1), self.cb_scope.currentData())

    def _edit_moved(self, idx, x0, y0, x1, y1):
        old = self.engine.edits[idx]
        self.engine.replace_edit(idx, Edit(old.kind, x0, y0, x1, y1, old.scope, old.page))
        self._edits_changed(); self.lst_edits.setCurrentRow(idx)

    def undo_edit(self):
        if self.engine.edits:
            self._remove_edit(len(self.engine.edits) - 1)

    def _remove_edit(self, k):
        if 0 <= k < len(self.engine.edits):
            self.engine.remove_edit(k)
            self._edits_changed()

    def clear_edits(self):
        if self.engine.edits and QMessageBox.question(self, APP_NAME, "Remover todas as edições deste documento?") == QMessageBox.Yes:
            self.engine.clear_edits()
            self._edits_changed()

    def _list_selected(self, row):
        self.view_orig.set_selected(row)
        if 0 <= row < len(self.engine.edits):
            e = self.engine.edits[row]
            if e.scope == "page" and e.page != self.page and 0 <= e.page < self.engine.n:
                self.sp_page.setValue(e.page + 1)

    def _view_selected(self, idx):
        self.lst_edits.blockSignals(True); self.lst_edits.setCurrentRow(idx); self.lst_edits.blockSignals(False)

    def _edits_changed(self, save=True):
        sel = self.lst_edits.currentRow()
        self.lst_edits.blockSignals(True)
        self.lst_edits.clear()
        self.lst_edits.addItems([e.label() for e in self.engine.edits])
        if 0 <= sel < self.lst_edits.count():
            self.lst_edits.setCurrentRow(sel)
        self.lst_edits.blockSignals(False)
        has = bool(self.engine.edits)
        self.btn_undo.setEnabled(has); self.btn_rm.setEnabled(has); self.btn_clear.setEnabled(has)
        self.lst_edits.setVisible(has); self.lb_edits_empty.setVisible(not has)
        self.btn_suggest.setEnabled(self.engine.n >= 2)
        self.btn_doubts.setEnabled(self.engine.n >= 1)
        if save and self.engine.n:
            try:
                if has:
                    self.engine.save_edits(self._project_file())
                elif self._project_file().exists():
                    self._project_file().unlink()
            except Exception as ex:
                self._soft_error("Não consegui salvar as edições deste PDF (elas valem só até fechar o programa)", ex)
        self._refresh_overlay()
        self._schedule()

    def _refresh_overlay(self):
        edits = [(k, e.kind, e.x0, e.y0, e.x1, e.y1) for k, e in enumerate(self.engine.edits) if e.applies(self.page)]
        self.view_orig.set_overlay(self._items, edits, self.ck_over.isChecked())

    def _show_context(self, hit, gpos):
        m = QMenu(self)
        scopes = list(SCOPES.items())

        def submenu(title, kind, rect):
            sm = m.addMenu(title)
            for sc, label in scopes:
                sm.addAction(label.capitalize()).triggered.connect(lambda _=False, s=sc: self._add_edit(kind, rect, s))

        if hit["edit"] >= 0:
            idx = hit["edit"]
            m.addAction("Remover esta edição").triggered.connect(lambda: self._remove_edit(idx))
            sm = m.addMenu("Mudar onde se aplica")
            for sc, label in scopes:
                sm.addAction(label.capitalize()).triggered.connect(lambda _=False, s=sc: self._change_scope(idx, s))
        else:
            fx, fy = hit["pos"]
            item, col = hit["item"], hit["col"]
            pad = 0.002
            if item or col:
                base = item if (item and item[0] in ("fig", "fixed")) else (col or item)
                rect = tuple(base[1:5])
                sm = m.addMenu("Corrigir esta região detectada")
                for label, k in (("É uma tabela", "table"), ("É uma imagem (figura)", "figure"), ("É texto normal", "text")):
                    ssm = sm.addMenu(label)
                    for sc, sl in scopes:
                        ssm.addAction(sl.capitalize()).triggered.connect(lambda _=False, kk=k, s=sc: self._add_edit(kk, rect, s))
                m.addSeparator()
            if item:
                kind, x0, y0, x1, y1 = item
                nome = {"fig": "esta figura", "line": "esta linha", "fixed": "esta linha (tabela)"}[kind]
                submenu(f"Excluir {nome}", "exclude", (x0 - pad, y0 - pad, x1 + pad, y1 + pad))
                if col:
                    submenu("Excluir este bloco de texto", "exclude", col[1:5])
                    submenu("Manter este bloco como figura", "figure", col[1:5])
                m.addSeparator()
                submenu("Excluir tudo acima daqui", "exclude", (0, 0, 1, max(0.0, y0 - pad)))
                submenu("Excluir tudo abaixo daqui", "exclude", (0, min(1.0, y1 + pad), 1, 1))
            else:
                a = m.addAction("Nada detectado aqui"); a.setEnabled(False)
                m.addSeparator()
                submenu("Excluir tudo acima deste ponto", "exclude", (0, 0, 1, fy))
                submenu("Excluir tudo abaixo deste ponto", "exclude", (0, fy, 1, 1))
        m.exec(gpos)

    def _change_scope(self, idx, scope):
        old = self.engine.edits[idx]
        self.engine.replace_edit(idx, Edit(old.kind, old.x0, old.y0, old.x1, old.y1, scope, self.page if scope == "page" else -1))
        self._edits_changed()

    # ------------------------------------------------------------ sugestão de cabeçalhos
    def _start_suggest(self, auto: bool):
        if self.engine.n < 2:
            return
        self.btn_suggest.setEnabled(False)
        self.status.setText("Procurando cabeçalhos e rodapés repetidos…")
        self.sth = SuggestThread(self.engine, self._params())
        self.sth.progress.connect(lambda a, b: self.status.setText(f"Procurando cabeçalhos e rodapés… {a}/{b}"))
        self.sth.result.connect(lambda sugg: self._suggest_done(sugg, auto))
        self.sth.failed.connect(lambda tb: (self.status.setText("Erro ao procurar sugestões."), print(tb, file=sys.stderr), self.btn_suggest.setEnabled(True)))
        self.sth.start()

    def _suggest_done(self, sugg, auto):
        self.btn_suggest.setEnabled(self.engine.n >= 2)
        self._pending_sugg = sugg
        if not sugg:
            self.status.setText("Não encontrei cabeçalhos ou rodapés repetidos.")
            if not auto:
                QMessageBox.information(self, APP_NAME, "Não encontrei cabeçalhos, rodapés ou números de página que se repitam.")
            return
        n = len(sugg)
        self.status.setText(f"{n} região(ões) repetida(s) encontrada(s).")
        if auto:
            self.infobar.show_message(
                f"Encontrei {n} {'região' if n == 1 else 'regiões'} que se repete{'' if n == 1 else 'm'} nas páginas "
                "(cabeçalho, rodapé ou número de página). Quer revisar e excluir?", "Revisar…")
        else:
            self._review_suggestions()

    def _review_suggestions(self):
        if not self._pending_sugg:
            return
        self._sd = SuggestDialog(self, self._pending_sugg)
        self._sd.highlight.connect(self._on_highlight)
        self._sd.applied.connect(self._apply_suggestions)
        self._sd.show()
        self._center_on_parent(self._sd)
        self._on_highlight(self._pending_sugg[0])      # destaca o primeiro item já ao abrir

    def _center_on_parent(self, dlg):
        """Centraliza o diálogo sobre a janela principal e garante que fique dentro da tela."""
        scr = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        g = self.frameGeometry()
        x = g.center().x() - dlg.width() // 2
        y = g.center().y() - dlg.height() // 2
        x = max(scr.left() + 8, min(x, scr.right() - dlg.width() - 8))
        y = max(scr.top() + 8, min(y, scr.bottom() - dlg.height() - 8))
        dlg.move(x, y)

    def _on_highlight(self, s):
        if s is None:
            self.view_orig.set_hint(None); return
        e = s.edit
        self.view_orig.set_hint((e.x0, e.y0, e.x1, e.y1))
        if s.sample_page != self.page:
            self.sp_page.setValue(s.sample_page + 1)

    def _apply_suggestions(self, edits):
        for e in edits:
            self.engine.add_edit(e)
        self._pending_sugg = []
        self.infobar.setVisible(False)
        self._edits_changed()

    # ------------------------------------------------------------ preview
    def _page_changed(self, v):
        self.page = v - 1
        self._update_nav()
        self._sync_thumbs()
        self._refresh_overlay()
        self._schedule(map_too=False)

    def _update_nav(self):
        has = self.engine.n > 0
        self.btn_prev.setEnabled(has and self.page > 0)
        self.btn_next.setEnabled(has and self.page < self.engine.n - 1)
        self.btn_conv.setEnabled(has)

    def _schedule(self, *_, map_too=True):
        if self.engine.n:
            self.status.setText("Atualizando…")
            self.timer.start()
            if map_too:
                self.map_timer.start()

    def _run_preview(self):
        if not self.engine.n:
            return
        self.gen += 1
        p = self._params()
        self.pool.start(PreviewJob(self.gen, self.engine, self.page, p, self._device(), self._fmt(), 12.0 * p.size, self.sig))

    def _on_done(self, gen, small, items, outs, info, secs):
        if gen != self.gen:
            return
        self._font = info
        self._refresh_value_labels()
        self.view_orig.set_image(to_pixmap(small))
        self._items = items
        self._refresh_overlay()
        self.out_pages = outs
        self.out_idx = min(self.out_idx, max(0, len(outs) - 1))
        self._show_out()
        if self._fmt() == "epub":
            self.status.setText(f"Prévia do EPUB · página {self.page + 1} de {self.engine.n} · {len(outs)} tela(s) · {secs:.1f} s. "
                                "No aparelho você escolhe o tamanho da letra.")
        else:
            self.status.setText(f"Página {self.page + 1} de {self.engine.n} · {len(outs)} página(s) de saída · atualizado em {secs:.1f} s. "
                                "O preview mostra só esta página; no arquivo final o texto flui entre as páginas.")

    def _on_failed(self, gen, tb):
        if gen == self.gen:
            self.status.setText("Erro ao gerar o preview (veja o console).")
            print(tb, file=sys.stderr)

    def _out_step(self, d):
        self.out_idx = max(0, min(len(self.out_pages) - 1, self.out_idx + d))
        self._show_out()

    def _show_out(self):
        if not self.out_pages:
            self.view_out.set_image(None); self.lb_out.setText("—")
            self.btn_op.setEnabled(False); self.btn_on.setEnabled(False)
            return
        pg = self.out_pages[self.out_idx]
        self.view_out.set_image(to_pixmap(np.pad(pg, ((6, 6), (6, 6), (0, 0)) if pg.ndim == 3 else 6, constant_values=40)))
        self.lb_out.setText(f"{self.out_idx + 1} de {len(self.out_pages)}")
        self.btn_op.setEnabled(self.out_idx > 0); self.btn_on.setEnabled(self.out_idx < len(self.out_pages) - 1)

    # ------------------------------------------------------------ conversão
    def convert_dialog(self):
        if not self.engine.n:
            return
        if self._fmt() == "epub" and not self._has_text:
            ok, why = ocrmod.available()
            if not ok:
                QMessageBox.information(self, APP_NAME, "Este PDF é só imagem e o OCR não está disponível nesta instalação.")
                return
            if QMessageBox.question(self, APP_NAME, "Este PDF é só imagem. Para gerar o EPUB é preciso reconhecer o texto (OCR) primeiro. "
                                    "Quer fazer isso agora? Depois a conversão continua.") == QMessageBox.Yes:
                self._start_ocr(then_convert=True)
            return
        stem = Path(self.engine.path).stem
        dev, fmt = self._device(), self._fmt()
        if fmt == "epub":
            name, filt = f"{stem}.epub", "EPUB (*.epub)"
        else:
            name, filt = f"{stem} - {dev['id']}.pdf", "PDF (*.pdf)"
        dst, _ = QFileDialog.getSaveFileName(self, "Salvar arquivo convertido", str(Path(self.engine.path).with_name(name)), filt)
        if not dst:
            return
        self.btn_conv.setEnabled(False); self.pb.setVisible(True); self.pb.setValue(0); self.btn_cancel.setVisible(True)
        self.status.setText("Convertendo…")
        self.th = ConvertThread(self.engine, dst, self._params(), dev, fmt)
        self.th.progress.connect(lambda a, b: (self.pb.setMaximum(b), self.pb.setValue(a), self.status.setText(f"Convertendo… {a} de {b} páginas")))
        self.th.finished_ok.connect(self._conv_ok)
        self.th.failed.connect(self._conv_fail)
        self.btn_cancel.clicked.connect(self.th.cancel)
        self.th.start()

    def _conv_end(self):
        self.pb.setVisible(False); self.btn_cancel.setVisible(False); self.btn_conv.setEnabled(True)
        try:
            self.btn_cancel.clicked.disconnect()
        except Exception:
            pass

    def _conv_ok(self, n, dst):
        self._conv_end()
        if n == 0:
            self.status.setText("Conversão cancelada."); return
        self.status.setText(f"Pronto: {n} páginas salvas em {dst}")
        self.last_output = dst
        self.btn_send.setEnabled(True)
        if self.opds is not None:
            self.opds.add(dst)
        auto_msg = ""
        if self.conn_settings.get("auto_calibre"):
            cal = targets.find_calibre()
            if cal:
                ok, msg = targets.calibre_add(cal, dst)
                auto_msg = "\n\nCalibre: " + ("adicionado à biblioteca." if ok else msg)
        extra = ("\n\nO Kindle não lê EPUB direto: converta para AZW3 no Calibre, use o KOReader ou o “Enviar para o Kindle”."
                 if dst.lower().endswith(".epub") else "")
        box = QMessageBox(self); box.setWindowTitle(APP_NAME); box.setIcon(QMessageBox.Information)
        box.setText(f"Pronto! {n} páginas salvas em:\n{dst}{extra}{auto_msg}")
        send = box.addButton("Enviar ou abrir com…", QMessageBox.AcceptRole); box.addButton("Fechar", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is send:
            self.show_send()

    def _conv_fail(self, tb):
        self._conv_end()
        QMessageBox.critical(self, APP_NAME, "Erro na conversão:\n" + tb[-800:])

    # ------------------------------------------------------------ configurações
    def _load_settings(self):
        try:
            d = json.loads(settings_path().read_text(encoding="utf-8"))
        except Exception:
            d = {}
        i = self.cb_dev.findData(d.get("device", "a4"))
        self.cb_dev.blockSignals(True); self.cb_dev.setCurrentIndex(max(0, i)); self.cb_dev.blockSignals(False)
        j = self.cb_preset.findText(d.get("preset", ""))
        if j >= 0:
            self.cb_preset.blockSignals(True); self.cb_preset.setCurrentIndex(j); self.cb_preset.blockSignals(False)
        k = self.cb_fmt.findData(d.get("format", "pdf"))
        self.cb_fmt.blockSignals(True); self.cb_fmt.setCurrentIndex(max(0, k)); self.cb_fmt.blockSignals(False)
        self.theme_pref = d.get("theme", "auto") if d.get("theme", "auto") in ("auto", "light", "dark") else "auto"
        self.btn_thumbs.setChecked(bool(d.get("thumbs", True)))
        self.conn_settings["auto_calibre"] = bool(d.get("auto_calibre", False))
        self.check_updates = bool(d.get("check_updates", True))
        self.update_checked = float(d.get("update_checked", 0) or 0)
        self.update_skip = str(d.get("update_skip", ""))
        self.thumb_panel.setVisible(self.btn_thumbs.isChecked())
        self._device_changed()

    def closeEvent(self, e):
        self._stop_workers()
        if self.opds is not None:
            self.opds.stop(); self.opds = None
        try:
            settings_path().write_text(json.dumps({"device": self.cb_dev.currentData(), "preset": self.cb_preset.currentText(),
                                                   "format": self._fmt(), "theme": self.theme_pref,
                                                   "thumbs": self.btn_thumbs.isChecked(),
                                                   "auto_calibre": bool(self.conn_settings.get("auto_calibre")),
                                                   "check_updates": self.check_updates, "update_checked": self.update_checked,
                                                   "update_skip": self.update_skip}, ensure_ascii=False), encoding="utf-8")
        except Exception as ex:
            log.warning("não salvou a configuração: %r", ex)
        super().closeEvent(e)


def main(argv=None):
    app = QApplication(argv or sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(branding.app_icon())
    w = MainWindow()
    w.show()
    for a in (argv or sys.argv)[1:]:
        if a.lower().endswith(".pdf"):
            w.open_file(a); break
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
