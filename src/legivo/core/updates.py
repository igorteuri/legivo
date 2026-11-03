"""Aviso de nova versão: consulta a última versão publicada nas Releases do GitHub.

Só lê (GET) a página pública de releases; não envia nada além do pedido HTTP comum (o GitHub vê o IP e o
nome do programa). O usuário pode desligar a consulta na tela Sobre. Sem dependências além da biblioteca padrão.
"""
from __future__ import annotations
import json
import re
import urllib.request
from dataclasses import dataclass, field

REPO = "igorteuri/legivo"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE_RELEASES = f"https://github.com/{REPO}/releases"


@dataclass
class Update:
    version: str                    # "0.12.0"
    url: str                        # página da versão (html)
    notes: str = ""
    assets: list = field(default_factory=list)      # [{"name", "url", "size"}]


def parse_version(text: str) -> tuple:
    """'v0.12.1' -> (0, 12, 1). Ignora sufixos como '-beta' (versão de teste vale menos que a final)."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)(.*)$", text or "")
    if not m:
        return ()
    nums = tuple(int(x) for x in m.group(1).split("."))
    nums = nums + (0,) * (3 - len(nums))
    return nums + ((0,) if m.group(2).strip() else (1,))


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return bool(a) and bool(b) and a > b


def from_release(data: dict) -> Update | None:
    """Converte a resposta da API do GitHub. Rascunhos e pré-lançamentos não contam."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if not parse_version(tag):
        return None
    assets = [{"name": a.get("name", ""), "url": a.get("browser_download_url", ""), "size": a.get("size", 0)}
              for a in data.get("assets", []) if isinstance(a, dict)]
    return Update(tag.lstrip("vV"), str(data.get("html_url") or PAGE_RELEASES), str(data.get("body") or "")[:2000], assets)


def fetch_latest(current: str, timeout: float = 6.0, opener=None) -> Update | None:
    """Última versão publicada, ou None (sem internet, limite da API, nada publicado). Nunca levanta erro."""
    req = urllib.request.Request(API_LATEST, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": f"Legivo/{current}"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            return from_release(json.loads(r.read().decode("utf-8")))
    except Exception:
        return None


def check(current: str, timeout: float = 6.0, opener=None) -> Update | None:
    """A atualização, se a versão publicada for mais nova que a instalada."""
    up = fetch_latest(current, timeout, opener)
    return up if up and is_newer(up.version, current) else None
