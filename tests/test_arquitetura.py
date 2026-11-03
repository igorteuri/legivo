"""Regras de arquitetura do CLAUDE.md que viram teste (para não se perderem com o tempo)."""
import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "src" / "legivo" / "core"


def _imports(f: Path) -> set[str]:
    tree = ast.parse(f.read_text(encoding="utf-8"))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            out.add(("." * n.level) + (n.module or ""))
    return out


def test_core_does_not_import_gui_or_qt():
    """core/ precisa rodar via CLI e testes, sem interface."""
    bad = {}
    for f in CORE.glob("*.py"):
        hits = [m for m in _imports(f) if m.startswith(("PySide", "PyQt", "legivo.gui", "..gui", ".gui"))]
        if hits:
            bad[f.name] = hits
    assert not bad, f"core/ importando interface: {bad}"


def test_no_source_file_is_ignored_by_git():
    """Regressão: a regra 'Legivo/' do .gitignore (pasta do executável) também pegava 'src/legivo/' no
    Windows (sem diferença de maiúsculas), e 16 arquivos do programa ficaram fora do git desde a v0.8.0."""
    import shutil
    import subprocess
    import pytest
    root = CORE.parents[2]
    if not shutil.which("git") or not (root / ".git").exists():
        pytest.skip("sem git")
    out = subprocess.run(["git", "ls-files", "--others", "--ignored", "--exclude-standard", "src", "tests", "tools"],
                         cwd=root, capture_output=True, text=True).stdout.splitlines()
    bad = [f for f in out if "__pycache__" not in f and ".pytest_cache" not in f and not f.endswith(".pyc")]
    assert not bad, f"arquivos do código ignorados pelo .gitignore: {bad}"


def test_gui_has_no_silent_except_around_user_data():
    """Falha ao carregar/salvar as edições do usuário não pode ser engolida em silêncio (perda de trabalho)."""
    import re
    src = (CORE.parent / "gui" / "app.py").read_text(encoding="utf-8")
    for trecho in ("load_edits", "save_edits"):
        for m in re.finditer(trecho, src):
            bloco = src[m.start(): m.start() + 400]
            ex = re.search(r"except Exception(?: as \w+)?:\n(\s+)(\S.*)", bloco)
            assert ex and ex.group(2) != "pass", f"except silencioso perto de {trecho}"
