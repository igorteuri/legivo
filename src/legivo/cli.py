"""Linha de comando: python -m legivo.cli entrada.pdf -o saida.pdf --dev kpw --preset NOME"""
from __future__ import annotations
import argparse, time
from .core.engine import Engine, load_devices
from .core.params import PRESETS, preset


def get_device(dev_id: str) -> dict:
    for d in load_devices():
        if d["id"] == dev_id:
            return d
    raise SystemExit("Dispositivo desconhecido: " + dev_id + ". Disponíveis: " + ", ".join(d["id"] for d in load_devices()))


def main():
    ap = argparse.ArgumentParser(prog="legivo")
    ap.add_argument("entrada"); ap.add_argument("-o", "--saida", required=True)
    ap.add_argument("--dev", default="a4"); ap.add_argument("-p", "--paginas", help="ex.: 1-5")
    ap.add_argument("--preset", default=list(PRESETS)[0], choices=list(PRESETS))
    ap.add_argument("--size", type=float, help="tamanho do texto (1.0 = padrão)")
    ap.add_argument("--no-wrap", action="store_true")
    ap.add_argument("--edits", help="arquivo JSON com edições manuais (exportado pela interface)")
    a = ap.parse_args()
    p = preset(a.preset)
    if a.size: p.size = a.size
    if a.no_wrap: p.wrap = False
    pr = None
    if a.paginas:
        s, _, e = a.paginas.partition("-"); pr = range(int(s) - 1, int(e or s))
    t = time.time(); eng = Engine(); eng.open(a.entrada)
    if a.edits: eng.load_edits(a.edits)
    n = eng.convert(a.saida, p, get_device(a.dev), pr)
    print(f"{n} páginas em {time.time() - t:.1f}s -> {a.saida}")


if __name__ == "__main__":
    main()
