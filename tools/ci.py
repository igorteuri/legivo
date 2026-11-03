"""Verificação única do Legivo: roda tudo em sequência e para no primeiro erro.

  py -3.11 tools/ci.py              # rápido (~15 s): sintaxe + lint + testes
  py -3.11 tools/ci.py --completo   # + verificações locais extras (se existirem), antes de gerar o .exe

Usado pelo hook de git (.githooks/pre-commit) e pelo hook do Claude Code (.claude/settings.json).
Saída 0 = tudo verde.
"""
from __future__ import annotations
import argparse
import compileall
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def step(nome: str, fn) -> None:
    t = time.perf_counter()
    print(f"==> {nome}", flush=True)
    ok = fn()
    print(f"    {'ok' if ok else 'FALHOU'} ({time.perf_counter() - t:.1f} s)", flush=True)
    if not ok:
        print(f"\nCI FALHOU em: {nome}")
        sys.exit(1)


def sintaxe() -> bool:
    return all(compileall.compile_dir(str(ROOT / d), quiet=1, force=False) for d in ("src", "tools", "tests"))


def lint() -> bool:
    ruff = shutil.which("ruff")
    if ruff is None:
        try:
            import ruff  # noqa: F401
            cmd = [sys.executable, "-m", "ruff"]
        except ImportError:
            print("    (ruff não instalado: lint pulado. Para ativar: py -3.11 -m pip install ruff)")
            return True
    else:
        cmd = [ruff]
    # só erros que quebram em tempo de execução: nome indefinido, import faltando, sintaxe
    return subprocess.run(cmd + ["check", "--select", "F821,F822,F823,E9,F63,F7", "src", "tools", "tests"], cwd=ROOT).returncode == 0


def testes(completo: bool) -> bool:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", LEGIVO_GOLDEN="completo" if completo else "rapido", QT_QPA_PLATFORM="offscreen")
    alvos = ["tests"] + (["local/golden"] if (ROOT / "local" / "golden" / "casos.json").exists() else [])   # verificações opcionais, só em máquinas que as têm
    return subprocess.run([sys.executable, "-m", "pytest", *alvos, "-q", "-p", "no:cacheprovider"], cwd=ROOT, env=env).returncode == 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--completo", action="store_true", help="inclui as verificações locais completas")
    a = ap.parse_args()
    t = time.perf_counter()
    step("sintaxe", sintaxe)
    step("lint (erros graves)", lint)
    step("testes" + (" (completo)" if a.completo else ""), lambda: testes(a.completo))
    print(f"\nOK: tudo verde em {time.perf_counter() - t:.0f} s")


if __name__ == "__main__":
    main()
