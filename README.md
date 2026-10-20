# reverter-legado

Ler um sistema legado, escrever o **contrato** do que ele promete, gerar o sistema novo
e um **avaliador que reprova** o que divergir. Três casos reais, com a evidência junto.

*Read a legacy system (source or just the binary), write the contract of what it
promises, generate the new system, and keep a cheap, exact evaluator that fails on any
divergence. Three real cases, evidence included.*

O caminho é sempre o mesmo:

    sistema legado ──ler──▶ contrato (JSON determinístico) ──gerar──▶ sistema novo
                                   ▲                                       │
                                   └────────── avaliador que reprova ◀─────┘

Mesma entrada, mesmos bytes: o contrato não tem data nem caminho de máquina, e o
avaliador refaz a leitura e compara seção por seção.

## Os casos

| pasta | o que faz | caso real |
|---|---|---|
| [`apps/delphi-contrato`](apps/delphi-contrato) | Delphi (.pas/.dfm/.dpr, ou só o .exe) → contrato com telas, eventos, regras e SQL → telas na web | HeidiSQL 12.21 lido só do executável e conferido contra o fonte; o código de 5 botões decompilado pelo REA e medido |
| [`apps/laravel-fastapi`](apps/laravel-fastapi) | Laravel (PHP) → contrato da API → app FastAPI → avaliador diferencial que roda os dois lado a lado | RealWorld (Laravel 9): todos os endpoints respondem igual; limite medido no BookStack |
| [`apps/rea-lab`](apps/rea-lab) | mede o REA (engenharia reversa por agente, com Ghidra) contra o fonte de um programa aberto | Chocolate Doom 3.1.1: funções conferidas uma a uma, e o formato WAD reconstruído só do binário |

Os números de cada caso estão no README da pasta e saem dos arquivos de evidência,
que os testes recalculam. Veja também o site: https://rea.genesisinnovation.io

## Rodar

Python 3.12 ou mais novo. O extrator Delphi só usa a biblioteca padrão:

    cd apps/delphi-contrato
    python3 -m delphi_contrato extrair tests/fixtures/cadastro -o contrato.json
    python3 -m delphi_contrato verificar contrato.json tests/fixtures/cadastro   # sai 1 se divergir

Testes:

    pip install pytest==8.4.2
    pytest -q apps/delphi-contrato/tests apps/rea-lab/tests
    pip install -r apps/laravel-fastapi/requirements.txt && pytest -q apps/laravel-fastapi/tests

Roda igual em Linux, macOS e Windows (no macOS, `python3` vem das Command Line Tools
ou de python.org). O REA, só para quando não há fonte, precisa de Node 22 e Java; a
receita do contêiner está em `apps/delphi-contrato/reverso/`.

## Licença

Código e textos: MIT (`LICENSE`). Arquivos derivados dos programas usados como caso
seguem a licença deles (GPL-2.0, MIT, BSD): veja `TERCEIROS.md`. Autores em `AUTORES.md`.

Feito pela [Genesis Innovation](https://genesisinnovation.io).
