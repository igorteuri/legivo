import sys
from pathlib import Path

# o pacote fica em src/ (sem instalação): todos os testes importam daqui
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
