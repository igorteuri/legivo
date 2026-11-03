"""Destinos dos arquivos gerados: Calibre e aparelhos conectados (Kindle, Kobo, KOReader).

Nada aqui depende da interface. As ações demoradas (conversão) devem rodar em thread.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ------------------------------------------------------------------ Calibre
def _calibre_dirs() -> list[Path]:
    dirs: list[Path] = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            dirs += [Path(base) / "Calibre2", Path(base) / "Programs" / "Calibre2"]
    dirs += [Path("/Applications/calibre.app/Contents/MacOS"), Path("/opt/calibre"), Path("/usr/bin")]
    return dirs


def find_calibre(extra_dirs: list[Path] | None = None) -> dict | None:
    """Procura as ferramentas do Calibre. Devolve {nome: caminho} ou None se não houver."""
    found: dict[str, str] = {}
    dirs = list(extra_dirs or []) + _calibre_dirs()
    for name in ("calibredb", "ebook-convert", "calibre", "ebook-viewer"):
        p = shutil.which(name)
        if not p:
            for d in dirs:
                for cand in (d / f"{name}.exe", d / name):
                    if cand.is_file():
                        p = str(cand)
                        break
                if p:
                    break
        if p:
            found[name] = p
    return found if ("calibredb" in found or "ebook-convert" in found) else None


def _run(cmd: list[str], timeout: int):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=CREATE_NO_WINDOW)


def _tail(text: str, n: int = 6) -> str:
    lines = [l for l in (text or "").strip().splitlines() if l.strip()]
    return "\n".join(lines[-n:])


def calibre_convert(calibre: dict, src: str, fmt: str = "azw3", profile: str = "kindle_pw") -> tuple[bool, str, str]:
    """Converte com o ebook-convert do Calibre (ex.: EPUB -> AZW3 para o Kindle).
    Devolve (ok, caminho_de_saida, mensagem)."""
    exe = calibre.get("ebook-convert")
    if not exe:
        return False, "", "O ebook-convert do Calibre não foi encontrado."
    out = str(Path(src).with_suffix("." + fmt))
    try:
        r = _run([exe, src, out, "--output-profile", profile], timeout=900)
    except Exception as e:
        return False, "", f"Falha ao executar o Calibre: {e}"
    if r.returncode != 0 or not Path(out).exists():
        return False, "", "O Calibre não conseguiu converter.\n" + _tail(r.stderr or r.stdout)
    return True, out, f"Convertido: {out}"


def calibre_add(calibre: dict, src: str) -> tuple[bool, str]:
    """Adiciona o arquivo à biblioteca do Calibre (calibredb add)."""
    exe = calibre.get("calibredb")
    if not exe:
        return False, "O calibredb não foi encontrado."
    try:
        r = _run([exe, "add", src], timeout=180)
    except Exception as e:
        return False, f"Falha ao executar o Calibre: {e}"
    text = (r.stdout or "") + "\n" + (r.stderr or "")
    if r.returncode == 0:
        return True, "Livro adicionado à biblioteca do Calibre. Se o Calibre estiver aberto, ele atualiza a lista sozinho em instantes."
    if "another calibre program" in text.lower() or "calibre" in text.lower() and "running" in text.lower():
        return False, ("O Calibre está aberto e bloqueia a biblioteca. Feche o Calibre e tente de novo, "
                       "ou arraste o arquivo para a janela do Calibre.")
    return False, "O Calibre não conseguiu adicionar o livro.\n" + _tail(text)


def calibre_open_viewer(calibre: dict, path: str) -> bool:
    exe = calibre.get("ebook-viewer") or calibre.get("calibre")
    if not exe:
        return False
    subprocess.Popen([exe, path], creationflags=CREATE_NO_WINDOW)
    return True


# ------------------------------------------------------------------ aparelhos conectados
def _roots() -> list[tuple[Path, bool]]:
    """(raiz, removível?) de cada volume montado."""
    out: list[tuple[Path, bool]] = []
    if os.name == "nt":
        import ctypes
        import string
        k = ctypes.windll.kernel32
        mask = k.GetLogicalDrives()
        for i, ch in enumerate(string.ascii_uppercase):
            if mask >> i & 1:
                root = f"{ch}:\\"
                out.append((Path(root), k.GetDriveTypeW(root) == 2))
    else:
        bases = [Path("/Volumes"), Path("/mnt")] + [p for p in Path("/media").glob("*")] + [p for p in Path("/run/media").glob("*")]
        for b in bases:
            if b.is_dir():
                out += [(c, True) for c in b.iterdir() if c.is_dir()]
    return out


def find_devices(roots: list[tuple[Path, bool]] | None = None) -> list[dict]:
    """Aparelhos de leitura conectados: Kindle, Kobo e KOReader (por marcas nas pastas do volume)."""
    found = []
    for root, removable in (roots if roots is not None else _roots()):
        try:
            has = lambda n: (root / n).is_dir()
            kindle = has("documents") and (has("system") or has(".active_content_sandbox") or has("koreader"))
            kobo = has(".kobo")
            koreader = has("koreader") or (root / ".adds" / "koreader").is_dir()
            if not (kindle or kobo):
                continue
            if not removable and not (kindle or kobo):
                continue
            name = "Kindle" if kindle else "Kobo"
            label = f"{name}{' com KOReader' if koreader else ''} ({str(root).rstrip(chr(92) + '/')})"
            found.append({"label": label, "root": str(root), "dest": str(root / "documents") if kindle else str(root),
                          "kind": name.lower(), "koreader": koreader})
        except OSError:
            continue
    return found


def copy_to_device(src: str, dest_dir: str) -> str:
    """Copia o arquivo para a pasta do aparelho e devolve o caminho final."""
    d = Path(dest_dir)
    d.mkdir(parents=True, exist_ok=True)
    dst = d / Path(src).name
    shutil.copy2(src, dst)
    return str(dst)


def reveal_in_folder(path: str):
    """Abre a pasta do arquivo (selecionando-o quando o sistema permite)."""
    p = Path(path)
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(p)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent)])


# ------------------------------------------------------------------ biblioteca do Calibre (somente leitura)
def calibre_library_path() -> str | None:
    """Pasta da biblioteca configurada no Calibre (lida do arquivo de configuração dele)."""
    import json
    bases = []
    if os.name == "nt":
        bases.append(Path(os.environ.get("APPDATA", "")) / "calibre")
    bases += [Path.home() / ".config" / "calibre", Path.home() / "Library" / "Preferences" / "calibre"]
    for b in bases:
        try:
            d = json.loads((b / "global.py.json").read_text(encoding="utf-8"))
            lib = d.get("library_path")
            if lib and (Path(lib) / "metadata.db").exists():
                return str(lib)
        except Exception:
            continue
    return None


def calibre_library_info(lib: str) -> dict | None:
    """Quantidade de livros da biblioteca, lendo o banco em modo somente leitura (nunca altera nada)."""
    import sqlite3
    db = Path(lib) / "metadata.db"
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=3)
        try:
            n = con.execute("select count(*) from books").fetchone()[0]
        finally:
            con.close()
        return {"path": str(lib), "books": int(n)}
    except Exception:
        return None


# ------------------------------------------------------------------ servidor de rede (OPDS) para o KOReader
MIME = {".epub": "application/epub+zip", ".pdf": "application/pdf", ".azw3": "application/vnd.amazon.mobi8-ebook",
        ".mobi": "application/x-mobipocket-ebook"}


def lan_ip() -> str:
    """Endereço do computador na rede local (sem enviar nenhum pacote)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class OpdsServer:
    """Catálogo OPDS simples: o KOReader (Rede > Catálogo OPDS) lista e baixa os arquivos registrados.
    Só serve arquivos que foram registrados com add(); nada mais do computador fica visível."""

    def __init__(self, port: int = 8765, host: str = "0.0.0.0"):
        import http.server
        import threading
        self.files: dict[str, str] = {}          # nome -> caminho
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body: bytes, ctype: str):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                from urllib.parse import unquote
                path = unquote(self.path.split("?")[0])
                if path in ("/", "/opds", "/opds/"):
                    return self._send(200, outer.feed(self.headers.get("Host", "")).encode("utf-8"),
                                      "application/atom+xml;profile=opds-catalog;kind=acquisition; charset=utf-8")
                if path.startswith("/file/"):
                    p = outer.files.get(path[6:])
                    if p and Path(p).is_file():
                        return self._send(200, Path(p).read_bytes(), MIME.get(Path(p).suffix.lower(), "application/octet-stream"))
                self._send(404, b"nao encontrado", "text/plain")

        self.httpd = http.server.ThreadingHTTPServer((host, port), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass

    def add(self, path: str):
        self.files[Path(path).name] = str(path)

    @property
    def url(self) -> str:
        return f"http://{lan_ip()}:{self.port}/opds"

    def feed(self, host: str = "") -> str:
        import datetime
        from urllib.parse import quote
        from xml.sax.saxutils import escape
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entries = []
        for name, p in sorted(self.files.items(), key=lambda kv: -Path(kv[1]).stat().st_mtime if Path(kv[1]).exists() else 0):
            if not Path(p).exists():
                continue
            mime = MIME.get(Path(p).suffix.lower(), "application/octet-stream")
            entries.append(f"<entry><title>{escape(Path(name).stem)}</title><id>urn:legivo:{escape(quote(name))}</id><updated>{now}</updated>"
                           f'<link rel="http://opds-spec.org/acquisition" href="/file/{quote(name)}" type="{mime}"/></entry>')
        return ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">'
                f"<id>urn:legivo:catalog</id><title>Legivo</title><updated>{now}</updated>"
                '<link rel="self" href="/opds" type="application/atom+xml;profile=opds-catalog;kind=acquisition"/>'
                '<link rel="start" href="/opds" type="application/atom+xml;profile=opds-catalog;kind=navigation"/>'
                + "".join(entries) + "</feed>")
