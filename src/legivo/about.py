"""Créditos e informações do programa (usado pela tela "Sobre" e por docs/CREDITS.md)."""
from __future__ import annotations
from . import __version__, __author__

APP_NAME = "Legivo"
TAGLINE = "PDF legível em qualquer tela"
DESCRIPTION = ("Converte artigos científicos, provas e livros de RPG em PDF ou EPUB confortáveis para Kindle, KOReader "
               "e outras telas, com pré-visualização na hora, e amplia documentos de várias colunas para quem tem baixa visão.")
LICENSE = "GNU General Public License v3.0 ou posterior (GPL-3.0-or-later)"
COPYRIGHT = f"Copyright © 2026 {__author__}"
REPOSITORY = "https://github.com/igorteuri/legivo"

# (nome, para que é usado, licença, autoria, endereço)
INSPIRATION = (
    "K2pdfopt",
    "Ideia e algoritmos de base: detecção de colunas por calhas em branco e reorganização de palavras (reflow). "
    "O Legivo é uma reimplementação independente, escrita em Python, inspirada no K2pdfopt.",
    "GPL-3.0", "Willus.com", "https://www.willus.com/k2pdfopt/",
)

TECHNOLOGIES = [
    ("PyMuPDF / MuPDF", "Leitura e renderização de PDF, extração de texto e prévia do EPUB", "AGPL-3.0", "Artifex Software", "https://pymupdf.readthedocs.io/"),
    ("PySide6 / Qt 6", "Interface gráfica", "LGPL-3.0", "The Qt Company", "https://www.qt.io/qt-for-python"),
    ("NumPy", "Análise e composição de imagens", "BSD-3-Clause", "NumPy Developers", "https://numpy.org/"),
    ("Pillow", "Redimensionamento e gravação de imagens", "HPND", "Jeffrey A. Clark e colaboradores", "https://python-pillow.org/"),
    ("RapidOCR", "Reconhecimento de texto (OCR) em PDFs de imagem", "Apache-2.0", "RapidAI", "https://github.com/RapidAI/RapidOCR"),
    ("PaddleOCR (modelos PP-OCR)", "Modelos de OCR usados pelo RapidOCR", "Apache-2.0", "Baidu / PaddlePaddle", "https://github.com/PaddlePaddle/PaddleOCR"),
    ("ONNX Runtime", "Execução dos modelos de OCR", "MIT", "Microsoft", "https://onnxruntime.ai/"),
    ("OpenCV", "Processamento de imagem do OCR", "Apache-2.0", "OpenCV team", "https://opencv.org/"),
    ("Python", "Linguagem de programação", "PSF-2.0", "Python Software Foundation", "https://www.python.org/"),
    ("PyInstaller", "Empacotamento do programa portátil", "GPL-2.0 com exceção", "PyInstaller Development Team", "https://pyinstaller.org/"),
]

OTHERS = [
    ("Calibre", "Integração opcional (não incluído): converter e adicionar livros à biblioteca", "GPL-3.0", "Kovid Goyal", "https://calibre-ebook.com/"),
    ("KOReader", "Leitor compatível (não incluído): lê os arquivos gerados no aparelho", "AGPL-3.0", "Comunidade KOReader", "https://koreader.rocks/"),
    ("Paleta Okabe-Ito", "Cores seguras para daltonismo nas marcações do original", "—", "Masataka Okabe e Kei Ito (2008)", "https://jfly.uni-koeln.de/color/"),
    ("UI/UX Pro Max", "Diretrizes de design de interface consultadas", "MIT", "Next Level Builder", "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill"),
    ("Claude Code", "Desenvolvimento assistido por inteligência artificial", "—", "Anthropic", "https://claude.com/claude-code"),
]


def plain_text() -> str:
    """Texto simples para copiar (suporte) e para a linha de comando."""
    lines = [f"{APP_NAME} {__version__} — {TAGLINE}", f"Desenvolvido por {__author__}", COPYRIGHT, f"Licença: {LICENSE}", "",
             "Inspirado em:", f"  {INSPIRATION[0]} ({INSPIRATION[3]}, {INSPIRATION[2]}) {INSPIRATION[4]}", "", "Tecnologias utilizadas:"]
    lines += [f"  {n} — {u} [{lic}] {a}" for n, u, lic, a, _ in TECHNOLOGIES]
    lines += ["", "Integrações, referências e ferramentas:"]
    lines += [f"  {n} — {u} [{lic}] {a}" for n, u, lic, a, _ in OTHERS]
    return "\n".join(lines)


def credits_markdown() -> str:
    def table(rows):
        out = ["| Componente | Uso | Licença | Autoria |", "|---|---|---|---|"]
        out += [f"| [{n}]({url}) | {u} | {lic} | {a} |" for n, u, lic, a, url in rows]
        return "\n".join(out)
    i = INSPIRATION
    return (f"# Créditos do {APP_NAME}\n\n"
            f"**{APP_NAME} {__version__}** — {TAGLINE}\n\n"
            f"Desenvolvido por **{__author__}**. {COPYRIGHT}. Licença: {LICENSE}.\n\n"
            f"## Inspiração\n\n**[{i[0]}]({i[4]})** ({i[3]}, {i[2]}): {i[1]}\n\n"
            f"## Tecnologias incluídas\n\n{table(TECHNOLOGIES)}\n\n"
            f"## Integrações, referências e ferramentas\n\n{table(OTHERS)}\n\n"
            "Os componentes acima pertencem aos seus autores e seguem as respectivas licenças. "
            "Este arquivo é gerado por python -m legivo.about.\n")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(credits_markdown())
