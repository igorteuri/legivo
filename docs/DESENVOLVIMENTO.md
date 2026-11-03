# Desenvolvimento

## Visão geral do código

```
src/legivo/
  core/       motor sem interface: render -> layout (colunas, linhas, figuras, tabelas) -> composição -> saída
              (engine.py organiza os estágios com cache; epub.py gera EPUB; ocr.py, targets.py, updates.py)
  gui/        interface Qt (janela principal, visualizações, diálogos, tema)
  profiles/   catálogo de aparelhos (devices.json)
  assets/     logo e ícones
tools/        build_exe.py (executável), release.py (zips e instaladores), make_icons.py
installer/    script do instalador (Inno Setup)
```

Regra de arquitetura: `core/` não importa `gui/` nem Qt (o motor roda também pela linha de comando); cada estágio é uma função pura para permitir cache e prévia incremental.

## Executável e instalador

Veja [BUILD.md](BUILD.md).
