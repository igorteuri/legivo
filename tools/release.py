"""Gera tudo o que vai para a página de Releases, em local/release/:

  Legivo-<versao>-portatil.zip        completo (com OCR), pasta portátil
  Legivo-<versao>-lite-portatil.zip   sem OCR, bem menor
  Legivo-Setup-<versao>.exe           instalador completo   (precisa do Inno Setup 6)
  Legivo-Setup-<versao>-lite.exe      instalador lite       (precisa do Inno Setup 6)
  SHA256SUMS.txt                      somas de verificação

Uso:  python tools/release.py [--so-zip]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REL = ROOT / "local" / "release"
sys.path.insert(0, str(ROOT / "src"))
from legivo import __version__ as VERSION  # noqa: E402


def find_iscc() -> str | None:
    hit = shutil.which("iscc")
    if hit:
        return hit
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        for sub in ("Inno Setup 6", r"Programs\Inno Setup 6"):
            p = Path(base or "") / sub / "ISCC.exe"
            if p.exists():
                return str(p)
    return None


def build(edition: str) -> Path:
    out = REL / edition
    args = [sys.executable, str(ROOT / "tools" / "build_exe.py"), "--out", str(out)] + (["--no-ocr"] if edition == "lite" else [])
    if subprocess.run(args, cwd=ROOT).returncode != 0:
        sys.exit(f"A compilação '{edition}' falhou.")
    st = REL / f"selftest_{edition}.json"
    subprocess.run([str(out / "Legivo.exe"), "--self-test", str(st)], cwd=ROOT)
    for _ in range(60):                          # o .exe não tem console: espera o arquivo aparecer
        if st.exists():
            break
        time.sleep(1)
    ok = st.exists() and json.loads(st.read_text(encoding="utf-8")).get("ok")
    if not ok:
        sys.exit(f"O autoteste da versão '{edition}' falhou (veja {st}).")
    return out


def make_zip(folder: Path, name: str) -> Path:
    dst = REL / name
    dst.unlink(missing_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(folder.rglob("*")):
            if f.is_file() and f.name != "legivo_config.json" and "legivo_projetos" not in f.parts:
                z.write(f, Path("Legivo") / f.relative_to(folder))
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--so-zip", action="store_true", help="não tenta gerar o instalador")
    a = ap.parse_args()
    REL.mkdir(parents=True, exist_ok=True)
    made = []
    iscc = None if a.so_zip else find_iscc()
    for edition, tag in (("full", ""), ("lite", "-lite")):
        folder = build(edition)
        made.append(make_zip(folder, f"Legivo-{VERSION}{tag}-portatil.zip"))
        if iscc:
            r = subprocess.run([iscc, "/Qp", f"/DAppVersion={VERSION}", f"/DSourceDir={folder}",
                                f"/DEdition={'lite' if tag else 'completa'}", str(ROOT / "installer" / "legivo.iss")], cwd=ROOT)
            if r.returncode == 0:
                made.append(REL / f"Legivo-Setup-{VERSION}{tag}.exe")
    if iscc is None and not a.so_zip:
        print("\nInstalador NÃO gerado: o Inno Setup 6 não está instalado (https://jrsoftware.org/isdl.php).")
    sums = []
    for f in made:
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        sums.append(f"{h}  {f.name}")
        print(f"{f.name:48s} {f.stat().st_size / 1e6:7.1f} MB")
    (REL / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
