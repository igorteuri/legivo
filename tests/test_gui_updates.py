"""Aviso de nova versão na janela principal (sem rede e sem tocar no legivo_config.json)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from legivo import __version__  # noqa: E402
from legivo.core.updates import Update  # noqa: E402
from legivo.gui import app as A  # noqa: E402


@pytest.fixture(scope="module")
def win():
    qa = QApplication.instance() or QApplication([])
    qa.setStyle("Fusion")
    w = A.MainWindow()
    w.check_updates = False            # nada de consulta real durante o teste
    yield w
    w._stop_workers()


def test_update_bar_shows_new_version_and_remembers_dismissal(win):
    win._upd_manual = None
    win.update_skip = ""
    win._update_found(Update("99.0.0", "https://github.com/igorteuri/legivo/releases/tag/v99.0.0"))
    assert not win.updbar.isHidden() and "99.0.0" in win.updbar.text.text() and __version__ in win.updbar.text.text()
    win.updbar._dismiss()
    assert win.update_skip == "99.0.0"
    win._update_found(Update("99.0.0", "x"))              # a mesma versão não volta a incomodar
    assert win.updbar.isHidden()
    win._update_found(Update("99.1.0", "x"))              # uma versão ainda mais nova, sim
    assert not win.updbar.isHidden()


def test_no_update_keeps_bar_hidden(win):
    win.updbar.setVisible(False)
    win._upd_manual = None
    win._update_found(None)
    assert win.updbar.isHidden()
