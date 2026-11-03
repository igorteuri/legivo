# Créditos do Legivo

**Legivo 0.11.1** — PDF legível em qualquer tela

Desenvolvido por **Igor Teuri**. Copyright © 2026 Igor Teuri. Licença: GNU General Public License v3.0 ou posterior (GPL-3.0-or-later).

## Inspiração

**[K2pdfopt](https://www.willus.com/k2pdfopt/)** (Willus.com, GPL-3.0): Ideia e algoritmos de base: detecção de colunas por calhas em branco e reorganização de palavras (reflow). O Legivo é uma reimplementação independente, escrita em Python, inspirada no K2pdfopt.

## Tecnologias incluídas

| Componente | Uso | Licença | Autoria |
|---|---|---|---|
| [PyMuPDF / MuPDF](https://pymupdf.readthedocs.io/) | Leitura e renderização de PDF, extração de texto e prévia do EPUB | AGPL-3.0 | Artifex Software |
| [PySide6 / Qt 6](https://www.qt.io/qt-for-python) | Interface gráfica | LGPL-3.0 | The Qt Company |
| [NumPy](https://numpy.org/) | Análise e composição de imagens | BSD-3-Clause | NumPy Developers |
| [Pillow](https://python-pillow.org/) | Redimensionamento e gravação de imagens | HPND | Jeffrey A. Clark e colaboradores |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | Reconhecimento de texto (OCR) em PDFs de imagem | Apache-2.0 | RapidAI |
| [PaddleOCR (modelos PP-OCR)](https://github.com/PaddlePaddle/PaddleOCR) | Modelos de OCR usados pelo RapidOCR | Apache-2.0 | Baidu / PaddlePaddle |
| [ONNX Runtime](https://onnxruntime.ai/) | Execução dos modelos de OCR | MIT | Microsoft |
| [OpenCV](https://opencv.org/) | Processamento de imagem do OCR | Apache-2.0 | OpenCV team |
| [Python](https://www.python.org/) | Linguagem de programação | PSF-2.0 | Python Software Foundation |
| [PyInstaller](https://pyinstaller.org/) | Empacotamento do programa portátil | GPL-2.0 com exceção | PyInstaller Development Team |

## Integrações, referências e ferramentas

| Componente | Uso | Licença | Autoria |
|---|---|---|---|
| [Calibre](https://calibre-ebook.com/) | Integração opcional (não incluído): converter e adicionar livros à biblioteca | GPL-3.0 | Kovid Goyal |
| [KOReader](https://koreader.rocks/) | Leitor compatível (não incluído): lê os arquivos gerados no aparelho | AGPL-3.0 | Comunidade KOReader |
| [Paleta Okabe-Ito](https://jfly.uni-koeln.de/color/) | Cores seguras para daltonismo nas marcações do original | — | Masataka Okabe e Kei Ito (2008) |
| [UI/UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | Diretrizes de design de interface consultadas | MIT | Next Level Builder |
| [Claude Code](https://claude.com/claude-code) | Desenvolvimento assistido por inteligência artificial | — | Anthropic |

Os componentes acima pertencem aos seus autores e seguem as respectivas licenças. Este arquivo é gerado por python -m legivo.about.

