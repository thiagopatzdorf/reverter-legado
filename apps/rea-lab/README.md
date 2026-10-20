# REA lab — apps/rea-lab
<!-- resumo: Mede o REA (engenharia reversa por agente, rea-agents 6.7.0 com Ghidra) contra o fonte de um programa aberto, que serve de gabarito: quantas funções e textos ele recupera, se o pseudo-código bate com o fonte e uma aplicação prática de ponta a ponta. Primeiro caso: o jogo Chocolate Doom 3.1.1, cujo formato de arquivo de dados (WAD) e cabeçalho de save foram documentados só pelo binário e conferidos contra o fonte. -->
<!-- ficha:inicio -->
| | |
|---|---|
| **Stack** | Python 3.12, só biblioteca padrão. REA (`rea-agents@6.7.0`, MIT) na imagem `rea-local:6.7.0` (Ghidra 12.1.4) |
| **Rodar** | `cd apps/rea-lab && python3 -m rea_lab {gabarito,compactar,medir,wad} ...` |
| **Testar** | `pip install pytest==8.4.2 && pytest -q apps/rea-lab/tests` |
| **Deploy** | nenhum: roda por demanda no papel `reverso` da máquina universal (`factory.manifest.json`) |
| **Estado** | primeiro caso medido em 2026-10-19 (Chocolate Doom 3.1.1) |
<!-- ficha:fim -->

Pedido (Thiago, 2026-10-19): *"temos que testar esse REA e ver aplicações práticas"*, com um
caso de jogo. O REA já tinha estreado no `apps/delphi-contrato` (HeidiSQL, Delphi); aqui ele
é medido num binário nativo C, com o fonte da mesma versão como gabarito.

## O alvo e por quê

| | |
|---|---|
| jogo | **Chocolate Doom 3.1.1**, port fiel do Doom (1993), em C |
| licença | GPL-2.0-or-later: estudo e redistribuição permitidos |
| binário | `chocolate-doom.exe` do zip oficial `chocolate-doom-3.1.1-win64.zip` (release do próprio projeto no GitHub), PE32+ x86-64 do MinGW, **sem tabela de símbolos** (875.520 bytes) |
| fonte | tag `chocolate-doom-3.1.1` do mesmo repositório |
| dado de teste | `freedoom1.wad` do Freedoom 0.13.0 (BSD-3-Clause), conteúdo livre compatível |

Escolhido porque é nativo e de tamanho médio (154 arquivos C no alvo), tem binário oficial e
fonte da mesma versão, tem formatos de arquivo de verdade (WAD e save) e não tem DRM, rede
obrigatória nem anti-cheat. URLs e sha256 (o do zip conferido contra o digest publicado na
release; o do Freedoom contra o CHECKSUM assinado) estão em `casos/chocolate-doom/caso.json`.

## Como o REA rodou

Sempre no contêiner `rea-local:6.7.0`, `--network none`, alvo montado `:ro`, `--cpus 2
--memory 8g`, sem cofre, um Ghidra por vez na máquina (`flock` na trava comum). A descoberta
que vale para os próximos casos: **cada comando da CLI reimporta o binário** (a análise do
Ghidra é efêmera; o `--snapshot` guarda só metadados), então a CLI paga ~3 minutos por
pergunta. O modo `rea --mcp` mantém a sessão aberta: uma importação de 134 s e depois cada
consulta em menos de 1 s (`casos/chocolate-doom/evidencia/rea-mcp.log`).

| passo | tempo medido |
|---|---|
| `rea analyze --provider ghidra` (CLI) | 206,9 s |
| `binary_overview` na sessão MCP (importação + análise) | 133,6 s |
| `list_procedures`, `list_strings`, `xrefs`, `procedure_pseudo_code` | 0,0 a 0,9 s cada |

O roteiro de cada função: texto que só aquela função usa no fonte (âncora) →
`list_strings` → `xrefs` → `resolve_containing_procedure` → `procedure_pseudo_code` e
`procedure_callees`. Nenhuma estrutura do executável foi lida por código nosso.

## Os números (`casos/chocolate-doom/evidencia/metricas.json`)

| medido | REA/Ghidra | fonte (gabarito) |
|---|---|---|
| procedimentos | 2.045 no total: 315 importados de DLL, 229 thunks, **1.501** próprios | **2.101** funções definidas (878 `static`), teto |
| nomes recuperados | 3 (2 `tls_callback`, 1 falso: `AfxRegisterMFCCtrlClasses`, assinatura de MFC num jogo SDL); **0** nomes do jogo | 2.067 nomes distintos |
| textos | 3.707 strings definidas | 2.429 literais únicos com 6+ caracteres; **2.182** achados no binário (89,8%) |

Leitura honesta: o fonte é teto, não alvo. O linker descarta objeto não usado, o `-O2`
embute função `static` pequena, e o binário traz funções do runtime do MinGW que não estão
no fonte do jogo; por isso 1.501 / 2.101 (71%) não é taxa de acerto. Os 10% de literais não
achados são, em boa parte, texto de ramo que não entra no Windows (`#ifdef`) e mensagem
embutida no lugar de uso.

## Doze funções importantes, pseudo-código contra fonte (`evidencia/funcoes.json`)

| função | âncora achou? | chamadas (fonte / REA) | textos | constantes | ramos | veredito |
|---|---|---|---|---|---|---|
| `D_DoomLoop` (laço principal) | sim | 13 / 15 | 1/1 | 3/3 | certos | **bate** |
| `G_DoSaveGame` (gravar save) | sim | 18 / 18 | 5/5 | 3/3 | certos | **bate** |
| `P_WriteSaveGameHeader` | sim | 4 / 3 | 1/1 | 4/4 | certos | **bate** |
| `P_ReadSaveGameHeader` | sim | 5 / 4 | 1/1 | 3/3 | certos | **bate** |
| `G_VanillaVersionCode` | via as duas acima | 0 / 0 | – | 2/2 | equivalentes | **bate** |
| `W_AddFile` (abre WAD) | sim | 15 / 15 | 8/8 | 5/6 | certos | parcial |
| `G_DoLoadGame` (ler save) | sim | 12 / 12 | 2/2 | 1/1 | **errados** | parcial |
| `W_ReadLump` | sim | 3 / 3 | 2/2 | – | **errados** | parcial |
| `W_GetNumForName` | sim (3 cópias) | 2 / 2 | 1/1 | – | **errados** | parcial |
| `TryRunTics` (entrada/rede por tic) | sim | 12 / 5 | 2/2 | 1/1 | estrutura certa | parcial |
| `M_LoadDefaults` (config) | sim | 5 / 6 | 5/5 | 3/3 | certos | parcial |
| `G_Ticker` | texto achado | – | – | – | – | **não achou** |

O que o REA acertou: em 11 de 12 a âncora levou à função certa; chamadas, textos e
constantes (`SAVEGAMESIZE` 0x2c000, limite de 4046 lumps, 24+16 bytes do save, `BACKUPTICS`
128) aparecem quase sempre; cinco funções saem equivalentes ao fonte.

O que errou, com causa:

- **retorno antecipado some** (`W_ReadLump`, `W_GetNumForName`, `G_DoLoadGame`): sai
  `if (ok) { }` vazio seguido do `I_Error`; lido ao pé da letra, a função sempre aborta.
  Quem usar o pseudo-código para portar código tem de conferir o assembly nesses pontos.
- **chamada por ponteiro perde os argumentos** (`W_Read` via `file_class->Read`): o offset
  do diretório do WAD só aparece no assembly (que o REA também devolve).
- **fronteira de função**: `_assert` não foi tratado como sem retorno e `M_LoadDefaults`
  ganhou três funções vizinhas coladas; `G_Ticker` nem virou função (o endereço que usa o
  texto está fora de qualquer procedimento).
- **inlining** apaga a forma: `TryRunTics` tem 5 chamadas contra 12 no fonte.
- **nomes**: binário sem símbolos não devolve nenhum nome do jogo; o único nome "achado"
  por assinatura é falso.

## Aplicação prática, de ponta a ponta: o formato WAD só pelo binário

O WAD é o arquivo de dados do Doom (mapas, sons, texturas); documentá-lo é o que permite
editor de mapa, mod e preservação. O formato foi escrito em `rea_lab/wad.py` **a partir do
pseudo-código e do assembly de `W_AddFile`** (cada campo cita o endereço), e só depois
conferido:

| campo | de onde saiu no binário | fonte (`w_wad.c`) |
|---|---|---|
| cabeçalho de 12 bytes no offset 0 | `0x1400231e4`: `EDX=0`, `R9D=0xc` | `wadinfo_t` (12 bytes) ✔ |
| `IWAD`/`PWAD` em 4 bytes | `strncmp(local_44,"IWAD",4)` | `identification[4]` ✔ |
| `numlumps` no +4 | `local_40`, usado como contagem | `numlumps` ✔ |
| `infotableofs` no +8 | `0x140023260: MOV EDX,[RSP+0x2c]` | `infotableofs` ✔ |
| entrada de 16 bytes: posição, tamanho, nome de 8 | passo `0x10`, `strncpy(...,8)` | `filelump_t` ✔ |
| PWAD com mais de 4046 lumps é recusado | `0xfce < numlumps` | mesmo limite ✔ |

Rodado no `freedoom1.wad` real (sha256 `7323bcc1…`, 28.795.076 bytes): IWAD, 3.163 lumps,
diretório no offset 28.744.468 terminando exatamente no fim do arquivo, nenhum lump fora do
arquivo, os 36 mapas E1M1–E4M9 (`evidencia/freedoom1.wad.json`). O teste
`test_layout_do_wad_tirado_do_binario_bate_com_os_structs_do_fonte` trava a conferência.

De quebra, o **cabeçalho do save** (`.dsg`) saiu inteiro das duas funções que usam
`"version %i"`: 24 bytes de descrição, 16 de versão (`version 109`, ou 106–108 conforme a
versão emulada, de `G_VanillaVersionCode`), 3 bytes de skill/episódio/mapa, 4 de jogadores
e `leveltime` em 3 bytes big-endian: 50 bytes, idêntico ao `P_WriteSaveGameHeader` do fonte.
Ficou documentado (`wad.SAVE_CABECALHO`); não foi lido de um save real, porque gerar um
exigiria rodar o jogo.

## Uso

    python3 -m rea_lab gabarito casos/chocolate-doom/caso.json <pasta com o fonte> -o gabarito.json
    python3 -m rea_lab compactar <list_procedures.json> <list_strings.json> <pasta>   # respostas MCP do REA
    python3 -m rea_lab medir <pasta> gabarito.json -o metricas.json
    python3 -m rea_lab wad freedoom1.wad

`rea_lab/rea.py` monta o contêiner e os comandos do REA em lista fechada (só leitura; nada
que execute o alvo), com a versão fixada igual à da fita e à do `delphi-contrato` (teste
reprova se divergirem).

## Aplicações que valem produto (e o que falta medir)

| ideia | por quê | falta medir |
|---|---|---|
| **documentar formato de arquivo** de programa sem documentação (save, config, exportação) | o caso acima: a âncora de texto acha a função de leitura e o pseudo-código dá campos, tamanhos e limites | o mesmo num formato sem texto de erro perto (âncora por `fopen`/`ReadFile`) e num binário C++ |
| **auditar o que o executável entregue faz** contra o fonte declarado (licitação, fornecedor) | textos 89,8% e chamadas batem; dá para dizer "esta função existe e chama isto" | taxa de falso positivo ao procurar algo que **não** está lá |
| **porte e preservação** de software legado (o mesmo trabalho do `delphi-contrato`, em C) | cinco funções saíram equivalentes | custo por função com o retorno perdido: quanto assembly um humano precisa ler |
| **suporte a mod** em jogo aberto sem documentação do formato | o WAD saiu completo | um jogo cujo formato não esteja na internet, para o resultado não ser memória do modelo |

## Limites conhecidos (medidos, não supostos)

- Contar funções do fonte é tolerante, não é compilador: `#if` não é avaliado e macro que
  gera função não é expandida. O número é teto.
- As colunas "chamadas (fonte)" foram contadas à mão no fonte da tag; as do REA vêm de
  `procedure_callees`. O veredito por função é do agente, com o motivo escrito em
  `funcoes.json`.
- Um binário só, uma plataforma (PE x86-64, MinGW, `-O2`). Binário com símbolos ou de outro
  compilador muda o número de nomes recuperados.
- A evidência bruta grande (lista completa de procedimentos e textos) vai em `.json.gz`, com
  sha256 em `caso.json`; o gabarito do fonte não é versionado (refaz-se do fonte da tag).
