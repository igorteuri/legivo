"""Gera o programa portátil na pasta ./Executavel (sempre substitui a versão anterior).

Uso:  python tools/build_exe.py                      # completa, com OCR (~330 MB)
      python tools/build_exe.py --no-ocr             # "lite", sem OCR (bem menor)
      python tools/build_exe.py --out outra/pasta    # em vez de ./Executavel

Como funciona:
  1. recusa continuar se o Legivo.exe estiver aberto (nunca fecha o seu programa);
  2. compila numa pasta temporária;
  3. ESPELHA o resultado em ./Executavel: atualiza o que mudou e apaga o que não existe mais,
     mas preserva legivo_config.json e legivo_projetos (suas configurações e edições);
  4. remove dist/, build/, *.spec e logs de compilações antigas.
A pasta ./Executavel nunca é apagada por inteiro, então janelas do Explorer abertas nela continuam válidas.
"""
from __future__ import annotations
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Executavel"
KEEP = {"legivo_config.json", "legivo_projetos"}      # dados do usuário, ao lado do executável
SEP = os.pathsep


def is_running() -> bool:
    if os.name != "nt":
        return False
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Legivo.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True)
    return "Legivo.exe" in (r.stdout or "")


def pyinstaller_cmd(work: Path, ocr: bool) -> list[str]:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--name", "Legivo",
           "--icon", str(ROOT / "src" / "legivo" / "assets" / "legivo.ico"),
           "--paths", str(ROOT / "src"), "--distpath", str(work / "dist"), "--workpath", str(work / "work"),
           "--specpath", str(work / "spec"),
           "--add-data", f"{ROOT / 'src' / 'legivo' / 'profiles' / 'devices.json'}{SEP}legivo/profiles",
           "--add-data", f"{ROOT / 'src' / 'legivo' / 'assets'}{SEP}legivo/assets"]
    if ocr:
        for pkg in ("rapidocr", "onnxruntime", "omegaconf"):
            cmd += ["--collect-all", pkg]
    else:
        cmd += ["--exclude-module", "cv2", "--exclude-module", "rapidocr", "--exclude-module", "onnxruntime"]
    for m in ("pymupdf.layout", "onnx", "scipy", "sklearn", "pandas", "matplotlib", "tkinter",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
              "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtNetwork"):
        cmd += ["--exclude-module", m]
    return cmd + [str(ROOT / "run_legivo.py")]


def mirror(src: Path, dst: Path):
    """Faz dst ficar igual a src (sem apagar a própria pasta dst nem os itens de KEEP)."""
    dst.mkdir(parents=True, exist_ok=True)
    wanted = {p.name for p in src.iterdir()}
    for p in dst.iterdir():
        if p.name not in wanted and p.name not in KEEP:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    for p in src.iterdir():
        t = dst / p.name
        if p.is_dir():
            mirror(p, t)
        elif not t.exists() or t.stat().st_size != p.stat().st_size or int(t.stat().st_mtime) != int(p.stat().st_mtime):
            shutil.copy2(p, t)


def cleanup():
    for name in ("dist", "build", "build_log.txt", "Legivo.spec"):
        p = ROOT / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()


# Arquivos que o programa não usa (a interface é só Qt Widgets) e que engordam a pasta
PRUNE = ("opengl32sw.dll", "opencv_videoio_ffmpeg*.dll", "Qt6Quick*.dll", "Qt6Qml*.dll", "Qt6Pdf*.dll",
         "Qt6VirtualKeyboard*.dll", "qpdf.dll", "qtvirtualkeyboardplugin.dll")


def prune(built: Path):
    """Remove DLLs que nada usa. Depois disso o --self-test confere se o programa continua inteiro."""
    for pat in PRUNE:
        for f in built.rglob(pat):
            if f.is_file():
                f.unlink()
    for d in built.rglob("translations"):
        if d.parent.name == "PySide6":
            shutil.rmtree(d, ignore_errors=True)


def folder_size(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ocr", action="store_true", help="não inclui o OCR (programa bem menor)")
    ap.add_argument("--out", default=str(OUT), help="pasta de saída (padrão: ./Executavel)")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    if out == OUT and is_running():
        sys.exit("O Legivo.exe está aberto. Feche-o e rode de novo (não vou fechar o seu programa).")
    work = Path(tempfile.mkdtemp(prefix="legivo_build_"))
    try:
        print("Compilando…")
        r = subprocess.run(pyinstaller_cmd(work, not a.no_ocr), cwd=ROOT)
        if r.returncode != 0:
            sys.exit("A compilação falhou.")
        built = work / "dist" / "Legivo"
        prune(built)
        print("Atualizando a pasta", out)
        mirror(built, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    cleanup()
    print(f"Pronto: {out / 'Legivo.exe'}  ({folder_size(out):.0f} MB)")


if __name__ == "__main__":
    main()
