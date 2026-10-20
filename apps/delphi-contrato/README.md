# Delphi → contrato — apps/delphi-contrato
<!-- resumo: Lê um sistema Delphi (.pas, .dpr, .dfm em texto ou binário TPF0) e escreve o contrato que o sistema novo tem de honrar: telas, eventos, regras com assinatura, SQL com tabelas e parâmetros, e cada clique ligado ao SQL que ele alcança; com avaliador que reprova contrato que deixou de ser o do fonte, e também do executável (.exe/.dll/.bpl) sem fonte, com o REA fixado para ir além das telas. -->
<!-- ficha:inicio -->
| | |
|---|---|
| **Stack** | Python 3.12, só biblioteca padrão. REA (`rea-agents@6.7.0`, MIT) por `npx`, só sem fonte |
| **Rodar** | `cd apps/delphi-contrato && python3 -m delphi_contrato extrair <pasta do projeto> -o contrato.json` |
| **Testar** | `pip install pytest==8.4.2 && pytest -q apps/delphi-contrato/tests` |
| **Deploy** | nenhum: roda por demanda no papel `reverso` da máquina universal (`factory.manifest.json`) |
| **Estado** | primeira versão em 2026-10-19, provada no exemplo `tests/fixtures/cadastro` |
<!-- ficha:fim -->

Pedido (2026-10-19): um professor universitário quer *"um tipo de sistema que converte
Delphi em um contrato novo"*. O Thiago pediu para anexar o REA
([morluto/rea](https://github.com/morluto/rea)) e usar esse pedido para estrear a máquina
universal.

## O que é o contrato

Não é tradução de código. É a lista do que o legado promete, e que o sistema novo
(qualquer linguagem) tem de cumprir:

| seção | o que tem | de onde vem |
|---|---|---|
| `formularios` | telas, componentes com as propriedades que importam (sem geometria) e eventos | `.dfm` (texto ou TPF0) + a classe na `.pas` |
| `operacoes` | cada evento → rotina → rotinas chamadas → SQL e tabelas que ele alcança | corpo das rotinas + datasets abertos (`Qry.Open`) |
| `unidades` | regras com assinatura (seção `interface`), registros, enumerações | `.pas` |
| `classes` | campos, métodos e propriedades com visibilidade | `.pas` |
| `sql` / `tabelas` | todo SQL embutido (código e `SQL.Strings` do `.dfm`), com tabelas e `:parametros` | `.pas` + `.dfm` |
| `pendencias` | o que não fecha: evento sem corpo, método sem corpo, SQL montado com variável, `.dfm` ilegível | tudo acima |
| `cobertura` | contagens, para comparar versões e medir o que falta | tudo acima |

Cada item aponta para arquivo e linha. Mesma entrada, mesmos bytes: o contrato não tem
data nem caminho absoluto, e as listas são ordenadas.

## Uso

    python3 -m delphi_contrato extrair <projeto> -o contrato.json      # o contrato
    python3 -m delphi_contrato relatorio contrato.json -o contrato.md  # para gente ler
    python3 -m delphi_contrato verificar contrato.json <projeto>       # sai 1 se divergir
    python3 -m delphi_contrato verificar contrato.json <projeto> --estrito  # pendência também reprova
    python3 -m delphi_contrato rea Sistema.exe [--aplicar]             # sem fonte: REA no executável

O `verificar` é o avaliador barato: refaz a extração e compara seção por seção. Contrato
editado à mão ou fonte que mudou depois aparecem ali, com o nome da seção.

O exemplo completo está em `tests/fixtures/`: o projeto `cadastro/` (cadastro de clientes
com um botão ligado a um handler sem corpo e um SQL montado com variável, de propósito),
o contrato gerado `cadastro.contrato.json` e o relatório `cadastro.contrato.md`.

## Sem fonte: o executável

`extrair` também aceita um `.exe`, `.dll` ou `.bpl` em vez da pasta (`binario.py`, só
biblioteca padrão; o arquivo é lido como bytes, nada é carregado nem executado):

| sai exato do executável | como |
|---|---|
| telas, componentes, ligações de dados, eventos, SQL dos componentes | o Delphi grava cada formulário como recurso RCDATA no formato TPF0, com o nome da classe |
| se o handler de cada evento existe | o nome do método na tabela de métodos publicados (sem ela o Delphi nem carrega o formulário) |
| SQL escrito no código | constantes de texto que começam com verbo SQL, em ANSI e UTF-16 (Delphi 2009+), fora da seção de recursos |

O que o executável **não** traz é o corpo das rotinas: a ligação clique → SQL fica vazia e o
contrato ganha a pendência `sem_fonte`. Para ela, o REA.

    python3 -m delphi_contrato extrair Sistema.exe -o contrato.json
    python3 -m delphi_contrato verificar contrato.json Sistema.exe

O teste monta um PE sintético com os formulários do exemplo (`tests/sintetico.py`) e prova
que as telas do `.exe` são as mesmas do fonte.

### O REA

Quando é preciso ir além das telas, o `rea` monta os comandos do REA com a versão fixada
(`delphi_contrato/rea.py`, `VERSAO_REA`), e só executa com `--aplicar`. O que o REA
devolve fica em `rea-evidencia/` com o sha256 de cada saída; saída que não é JSON não
conta como evidência, mesmo com exit 0. O REA precisa de Node ≥ 22.19 e, para binário
nativo, de Ghidra (Java). `python3 apps/factory/bin/factory-maquina.py conferir reverso`
diz o que falta no substrato.

A versão do REA está em dois lugares (código e fita) e o teste
`test_versao_do_rea_na_fita_diverge_da_do_codigo` reprova se divergirem. Atualizar o REA
é um diff revisado nos dois, nunca `@latest`.

## Caso real: HeidiSQL 12.21 (publicado em rea.genesisinnovation.io, aba Delphi; o antigo genesisinnovation.io/caso-delphi leva para lá)

O executável oficial (`heidisql.exe`, 25 MB, release v12.21) e o fonte Delphi do commit de release
(`effb854`, "Bump version for v12.21 release"; a tag `v12.21` aponta para o port em Lazarus):

| medido | resultado |
|---|---|
| contrato do `.exe` | 38 telas, 1.634 componentes, 1.264 eventos, 199 SQL, em ~5 s |
| `.exe` × fonte (`comparar`) | 34 de 34 telas do projeto idênticas: componentes, propriedades e eventos |
| achado só do `.exe` | `TfrmSyncDB` embutida sem classe: nada a abre, o linker removeu o código |
| versão web (`web` + `web/tela.mjs`) | 38 telas, 0 componente ou evento faltando (`conferir`) |

Os dados da página saem de `casos/heidisql.py`; o vídeo, de `casos/video/` (cena + gravador
quadro a quadro, `node casos/video/gravar.cjs <repo> <mp4> <jpg>`).

### O código dos botões, pelo REA (`casos/heidisql_rea.py`)

O `.exe` não traz o corpo dos handlers; o REA (Ghidra, sessão `rea mcp` num contêiner
descartável, sem rede) traz. Cinco handlers, cada um achado por um texto que só ele usa no
fonte: busca do texto → referências → função que contém → pseudo-código. O veredito sai de
`casos/heidisql-rea/marcas.json` (fato do fonte → texto que ele deixa no pseudo-código), não é
digitado; a evidência (pedidos, respostas, pseudo-código, tabela de métodos) fica em
`casos/heidisql-rea/evidencia/`.

| medido | resultado |
|---|---|
| análise inicial do `.exe` de 25 MB | 1.053 s, uma vez; cada pergunta depois, até 0,1 s |
| handlers iguais ao fonte | 3 de 5; os outros 2 só perdem o bloco `except` |
| fatos do caminho normal / do bloco de erro | 18 de 18 / 0 de 3 |
| função do REA = endereço da tabela de métodos publicados | 5 de 5 |
| achados pelo texto | 4 de 5: o 5º texto só existe dentro do `except`, então não há referência a seguir |

Regra que fica: no Delphi x64, código que só roda em exceção não aparece no pseudo-código do
Ghidra. O tratamento de erro de um handler migrado se confere à parte.

A receita da imagem do REA (entradas com sha256, imagem e sessão por fila) está em
`reverso/README.md`, com o servidor da sessão em `reverso/servidor.mjs`.

    python3 apps/delphi-contrato/casos/heidisql_rea.py [--exe heidisql.exe] \
        --saida apps/genesis-site/fonte/rea/delphi/rea.json

O caso real derrubou três suposições do leitor, cada uma virou teste: tipo procedural
(`procedure(...); cdecl;`, `procedure of object`) não abre rotina; pasta de projeto real mistura
demos de terceiros (por isso o `.dpr` como entrada); e handler ausente no `.exe` pode ser a tela
inteira morta (`tela_sem_codigo`), não 17 handlers soltos.

Comandos novos:

    python3 -m delphi_contrato extrair <projeto>.dpr -o contrato.json   # só as units do projeto
    python3 -m delphi_contrato comparar Sistema.exe <projeto>.dpr      # sai 1 se alguma tela divergir
    python3 -m delphi_contrato web Sistema.exe -o telas.json           # recusa se faltar algo do contrato

## No navegador, sem instalar nada (`navegador/`)

O mesmo pacote `delphi_contrato`, rodando no Pyodide 314.0.7 (Python 3.14 em WebAssembly), numa
página estática: o usuário arrasta o `.exe`/`.dll`/`.bpl`, os `.dfm` ou o `.zip` do projeto e baixa o
`contrato.json` e o relatório `.md`. O arquivo é lido na própria aba e não sai do computador.

    python3 apps/delphi-contrato/navegador/montar.py <destino> [--prefixo /experimente/]
    python3 apps/delphi-contrato/navegador/servir.py <destino>    # conferir local, com a CSP

| medido (Chromium 141 headless, 2026-10-20) | resultado |
|---|---|
| contrato baixado × CLI, mesmo arquivo | sha256 igual: `cadastro.zip`, `Cadastro.exe` sintético, o `heidisql.exe` real de 25 MB e o zip portable oficial dele (30 MB, 34 binários: a página acha o único com tela Delphi) |
| tamanho da pasta montada | 13,7 MB (Pyodide 13,5 MB; ~6,3 MB com gzip) |
| carga do motor (cache frio, servidor local) | ~2,4 s |
| extração | exemplo: 24–32 ms; `heidisql.exe`: 6,8 s (CPython: 5,6 s) |
| rede depois da carga | só GET dos arquivos da própria pasta; 0 pedido externo, 0 pedido com corpo, 0 violação de CSP |

O que entra na página e como ela diz o que equivale na CLI está em `navegador/ponte.py`. O Pyodide não
vai para o Git: o `montar.py` baixa o pacote do npm uma vez, confere o sha256 de cada arquivo contra
`navegador/pyodide.json` e guarda em `navegador/.cache/` (ou `$DELPHI_PYODIDE_CACHE`).
`tests/test_navegador.py` abre a página num Chromium headless e compara o sha256 do contrato baixado
com o da CLI.

**Para quem embute** (o site serve a pasta montada como está, em qualquer caminho, porque todo endereço
é relativo): a página é `index.html`, e o servidor precisa mandar a CSP do `manifesto.json` (o
`montar.py` já escreve `_headers` no formato do Cloudflare). O mínimo é
`script-src 'self' 'wasm-unsafe-eval'`, `worker-src 'self'` e `connect-src 'self'`. Sem
`'wasm-unsafe-eval'` o WebAssembly não compila; isso não libera `eval` de JavaScript. Os `.mjs` têm
de sair como `text/javascript` e o `.wasm` como `application/wasm`.

**Para agentes de IA**: a página funciona por cliques (`#arquivo`, botões com rótulo), marca
`body[data-estado]` (`carregando`, `pronto`, `extraindo`, `feito`, `erro`) e deixa o resultado em JSON
em `#resultado-json` (contrato inteiro em `#contrato-json`). Quando o navegador tem WebMCP
(`document.modelContext`, ou o antigo `navigator.modelContext`), registra `extrair_contrato` e
`comparar`. Medido: o Chromium 141 headless daqui não tem a API, nem com `--enable-features=WebMCP`;
o teste usa uma API simulada para provar que as duas ferramentas registram e devolvem o mesmo sha256.
Pela documentação do Chrome (não medido aqui), o WebMCP existe só no Chrome com a flag
`chrome://flags/#enable-webmcp-testing` ou em origin trial (Chrome 149 a 156), e Firefox e Safari
não o têm. Onde não existe, a página segue igual e `window.delphiContrato` dá a mesma API em JS.

### Perguntas do professor

**Roda no Mac?** No navegador, sim: Safari, Chrome ou Firefox recentes, sem instalar nada (a página
usa WebAssembly e módulo em Web Worker; medido no Chromium, não num Mac). A linha de comando
também, com Python ≥ 3.12. Atenção: o `python3` que vem com as Command Line Tools da Apple é o 3.9.6,
até no macOS Tahoe com Xcode 26 ([fórum da Apple](https://developer.apple.com/forums/thread/838682)), e
não serve. Instale o Python 3.12 ou mais novo pelo instalador de python.org (ou `brew install
python@3.12`) e rode `python3 -m delphi_contrato extrair ...` de dentro de `apps/delphi-contrato`.

**Dá para baixar um .exe para testar?** Não é preciso: a página é o "programa para baixar" que serve
para Windows, Mac e Linux de uma vez. Para quem precisa rodar sem internet, a opção mais barata medida
é o pacote como `zipapp` (`python3 -m zipapp`): um arquivo `.pyz` de 89 KB que roda com qualquer
Python ≥ 3.12 e dá o mesmo sha256 do contrato. No Windows sem Python instalado, o "embeddable package"
do python.org (3.12.10, 11,1 MB, só descompactar) mais o `.pyz` e um `.bat` resolvem, e dá para montar
isso daqui, sem máquina Windows. Executável nativo (PyInstaller e similares) não foi feito: precisa
de máquina Windows e Mac para compilar e assinar, e não temos nenhuma das duas para build.

## Limites conhecidos (medidos, não supostos)

- O leitor de Pascal é tolerante, não é compilador: `{$IFDEF}` não é avaliado (os dois
  ramos entram), e genéricos, `class helper` e `asm` não são interpretados.
- Chamada entre rotinas é achada **por nome**: uma variável com o mesmo nome de uma
  rotina vira chamada falsa. A operação lista o que chamou (`chama`) para conferir.
- SQL montado em tempo de execução vira pendência `sql_dinamico`: a tabela real só
  aparece rodando o sistema.
- Executável: só PE do Windows; executável comprimido (UPX e similares) precisa ser
  descomprimido antes. A presença do handler na tabela de métodos é procurada por nome nas
  seções de código e dados, não pela estrutura da VMT. Testado num PE sintético; o primeiro
  `.exe` real vai medir a cobertura de verdade.
