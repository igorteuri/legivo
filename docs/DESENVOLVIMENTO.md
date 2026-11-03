# Desenvolvimento

## Visão geral do código

```
src/legivo/
  core/       motor sem interface: render -> layout (colunas, linhas, figuras, tabelas) -> composição -> saída
              (engine.py organiza os estágios com cache; epub.py gera EPUB; ocr.py, targets.py, updates.py)
  gui/        interface Qt (janela principal, visualizações, diálogos, tema)
  profiles/   catálogo de aparelhos (devices.json)
  assets/     logo e ícones
tests/        testes automatizados (usam PDFs gerados na hora, sem arquivos de terceiros)
tools/        ci.py (verificação única), build_exe.py (executável), make_icons.py
installer/    script do instalador (Inno Setup)
```

Regras de arquitetura: `core/` não importa `gui/` nem Qt (há um teste para isso); cada estágio é uma função pura para permitir cache e prévia incremental.

## Verificação

```
python tools/ci.py     # sintaxe + ruff (erros graves) + testes, ~15 s
```

Toda correção de bug começa com um teste que reproduz o problema (vermelho) e só depois a correção (verde). Todo comportamento novo vem com teste do caso normal e de pelo menos um caso de borda.

## Regressão em documentos reais

`core/quality.py` mede, por página, quanto do texto original foi refeito, onde caiu o que não foi, quantas colunas/figuras/tabelas foram detectadas e se a ordem de leitura está trocada. Quem tem uma coleção própria de PDFs pode comparar essas métricas antes e depois de uma mudança no motor; os documentos de terceiros não fazem parte do repositório.

## Executável e instalador

Veja [BUILD.md](BUILD.md).
