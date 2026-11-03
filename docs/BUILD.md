# Gerar o executável portátil (Windows)

```
python -m pip install pymupdf numpy pillow PySide6 pyinstaller rapidocr onnxruntime
python tools/build_exe.py            # completa, com OCR
python tools/build_exe.py --no-ocr   # lite, sem OCR (bem menor)
python tools/build_exe.py --out outra/pasta
```

O resultado é **sempre a pasta `Executavel\`** na raiz do projeto (`Executavel\Legivo.exe`). A cada compilação:

1. se o `Legivo.exe` estiver aberto, a ferramenta para e avisa (nunca fecha o programa);
2. a compilação acontece numa pasta temporária;
3. a pasta `Executavel\` é **espelhada**: o que mudou é atualizado e o que não existe mais é apagado, mas `legivo_config.json` e `legivo_projetos\` (suas configurações, edições e cache de OCR) são preservados;
4. `dist\`, `build\`, `*.spec` e logs antigos são removidos.

A pasta `Executavel\` nunca é apagada por inteiro, então janelas do Explorer abertas nela continuam funcionando.

## Verificar o executável

```
Executavel\Legivo.exe --self-test saida.json
```

Confere as bibliotecas, a logo, o catálogo de aparelhos, a geração de EPUB e o OCR (reconhece uma frase com acentos). O `.exe` não tem console, por isso o resultado vai para o arquivo JSON.

## Ícones

`python tools/make_icons.py` gera `legivo.png` e `legivo.ico` a partir de `src/legivo/assets/legivo.svg` (fonte única da logo).

## Observações

- O PyMuPDF 2.0 importa `pymupdf.layout` (ONNX), que não usamos e quebra no executável: fica excluído.
- O OCR traz ONNX Runtime, OpenCV e os modelos PP-OCR (~230 MB a mais). Use `--no-ocr` para uma versão enxuta.
- O executável é gerado localmente (sem GitHub Actions).
- Depois da compilação a ferramenta remove DLLs que a interface não usa (OpenGL por software, Qt Quick/QML/PDF, FFmpeg do OpenCV, traduções do Qt). O `--self-test` confere que nada essencial foi embora.

## Instalador e página de Releases

```
python tools/release.py            # compila a versão completa e a lite, roda o autoteste de cada uma,
                                   # gera os .zip portáteis, os instaladores e o SHA256SUMS.txt em local/release/
python tools/release.py --so-zip   # sem instaladores
```

Os instaladores precisam do **Inno Setup 6** (grátis; o `release.py` o encontra sozinho). O script `installer/legivo.iss` instala só para o usuário atual em `%LocalAppData%\Programs\Legivo` (o Legivo grava as configurações ao lado do programa, e Program Files não permite isso) e usa um `AppId` fixo, então uma versão nova instala por cima da anterior.

Para publicar: crie a tag `vX.Y.Z` (o número precisa ser maior que o de `src/legivo/__init__.py` da versão anterior, é com ele que o aviso de atualização compara) e anexe os arquivos de `local/release/` na Release. A página do projeto (`docs/index.html`, servida pelo GitHub Pages) lê os arquivos da última Release sozinha.
