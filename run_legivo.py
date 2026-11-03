"""Ponto de entrada do Legivo (usado também pelo PyInstaller)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if len(sys.argv) >= 2 and sys.argv[1] in ("--version", "-V"):
    from legivo import __version__
    if sys.stdout:
        print(f"Legivo {__version__}")
    sys.exit(0)

if len(sys.argv) >= 3 and sys.argv[1] == "--self-test":
    from legivo.selftest import run
    sys.exit(run(sys.argv[2]))

from legivo.gui.app import main

if __name__ == "__main__":
    main()
