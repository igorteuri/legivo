# Integrações: Calibre, KOReader, Kindle e Kobo

Depois de converter, o botão **Enviar ou abrir com…** (ou a janela que aparece ao terminar) oferece:

## Calibre (gratuito, calibre-ebook.com)

O Legivo procura o Calibre no computador (PATH e pastas padrão do Windows). Não é incluído no programa.

| Botão | O que faz | Comando |
|---|---|---|
| Adicionar à biblioteca | coloca o arquivo na biblioteca padrão | `calibredb add arquivo` |
| Converter para AZW3 (Kindle) | gera `arquivo.azw3` ao lado do original | `ebook-convert arquivo arquivo.azw3 --output-profile kindle_pw` |
| Converter para MOBI (Kindle antigo) | idem, em MOBI | `ebook-convert ... .mobi` |
| Abrir no visualizador | abre no leitor do Calibre | `ebook-viewer arquivo` |

Se o Calibre estiver aberto, o `calibredb` não consegue usar a biblioteca (ela fica bloqueada). O Legivo avisa e sugere fechar o Calibre ou arrastar o arquivo para a janela dele.

## Aparelho conectado por USB (Kindle, Kobo, KOReader)

O Legivo reconhece o volume do leitor pelas pastas dele:

- **Kindle**: pasta `documents` (+ `system` ou `koreader`). Copia para `documents`.
- **Kobo**: pasta `.kobo`. Copia para a raiz.
- **KOReader**: pasta `koreader` (Kindle) ou `.adds/koreader` (Kobo); só informa que o EPUB é lido direto.

Também há "Escolher outra pasta…". Depois de copiar, ejete o aparelho com segurança. O KOReader pode precisar ser reaberto para listar o arquivo novo, e no Kindle convém fechar o KOReader antes de conectar o cabo.

## Qual formato usar

| Leitor | PDF | EPUB | AZW3/MOBI |
|---|---|---|---|
| Kindle (leitor nativo) | sim | não direto* | sim |
| Kindle com KOReader | sim | sim | — |
| Kobo | sim | sim | não |

\* O Kindle aceita EPUB pelo **Enviar para o Kindle** da Amazon (e-mail ou aplicativo), que converte; ou converta para AZW3 pelo Calibre.

## Conexões (botão no topo da janela principal)

A janela **Conexões** reúne o que dá para ligar antes de converter:

- **Calibre**: mostra se foi encontrado, a biblioteca dele (lida do arquivo de configuração do Calibre) e quantos livros tem. A contagem lê o banco em modo somente leitura, sem alterar nada. A opção *Adicionar à biblioteca do Calibre automaticamente depois de converter* usa o `calibredb add`.
- **KOReader por rede (Wi-Fi)**: o KOReader sabe abrir catálogos **OPDS**. O Legivo liga um pequeno servidor OPDS no computador; no KOReader você cadastra o endereço uma vez (menu de busca › Catálogo OPDS › + ) e baixa os livros pelo próprio aparelho. O servidor só mostra os arquivos disponibilizados (o último convertido ou os que você escolher), responde 404 para qualquer outra coisa e fica **desligado** até você ligá-lo. O Windows pode pedir permissão no firewall; computador e aparelho precisam estar na mesma rede.
- **Aparelho por USB**: mostra o que está conectado; o envio é feito em *Enviar ou abrir com…*.

## O que ainda não existe

- **SSH/SFTP do KOReader** (o KOReader também pode ser servidor SSH): não implementado, porque exigiria senha/chave e não pôde ser testado sem o aparelho.
- **Calibre sem fio** (plugin do KOReader): configurado nos próprios programas.
- **Kindle**: use *Enviar para o Kindle* (e-mail ou aplicativo da Amazon) ou converta para AZW3 pelo Calibre.
