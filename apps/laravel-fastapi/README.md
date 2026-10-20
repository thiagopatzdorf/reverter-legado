# Laravel → FastAPI — apps/laravel-fastapi
<!-- resumo: Lê um app Laravel (PHP) e escreve o contrato da API em JSON determinístico (rotas, validações, tabelas das migrations, models, resources, voláteis e pendências); gera dele um app FastAPI que roda (rotas, Depends para middleware, Pydantic das validações, SQLAlchemy das tabelas e o código do app traduzido sobre um runtime compatível); e mede com um avaliador diferencial que manda as mesmas requisições aos dois apps e compara status, corpo e banco. -->
<!-- ficha:inicio -->
| | |
|---|---|
| **Stack** | Python 3.12. Leitor de PHP: tree-sitter + tree-sitter-php (MIT). App gerado: FastAPI, Pydantic, SQLAlchemy |
| **Rodar** | `cd apps/laravel-fastapi && python3 -m laravel_fastapi extrair <app Laravel> -o contrato.json && python3 -m laravel_fastapi gerar contrato.json -o gerado/` |
| **Testar** | `pip install -r apps/laravel-fastapi/requirements.txt && pytest -q apps/laravel-fastapi/tests` |
| **Deploy** | nenhum: roda por demanda; o caso real roda em containers descartáveis `lf-*` |
| **Estado** | primeira versão em 2026-10-19, provada no RealWorld (Laravel 9): 19 de 19 endpoints respondem igual |
<!-- ficha:fim -->

Pedido (Thiago, 2026-10-19): *"Quero conversor de PHP e Laravel pra FastAPI."* Segue a forma do
`apps/delphi-contrato`: **ler → contrato JSON determinístico → gerar o sistema novo → avaliador que reprova.**

## O que sai de cada passo

**1. Contrato** (`contrato.py`, `php.py`). O fonte é lido pela árvore do tree-sitter, nunca por regex nem
rodando PHP. O corpo de cada método vai para o contrato num IR pequeno (listas JSON), com o nome de cada
classe já resolvido pelo `namespace`/`use`; o que o leitor não entende vira nó `?` com a linha, e pendência.

| seção | o que tem | de onde vem |
|---|---|---|
| `rotas` | método, caminho, parâmetros, middleware (grupo + rota), ação | `RouteServiceProvider` + `routes/*.php` (grupos, prefixo, nome, `apiResource`) |
| `validacoes` | regras de cada `FormRequest` (literais quando dá), onde os dados moram (`validationData`) | `app/Http/Requests` |
| `tabelas` | colunas com tipo, nulo, tamanho, padrão, único, chave estrangeira e `onDelete` | `database/migrations` (`Schema::create/table`) |
| `models` | tabela, `fillable`, `hidden`, `casts`, relações, escopos | classes Eloquent |
| `recursos` | `wrap`, `collects`, campos do `toArray` | `JsonResource`/`ResourceCollection` |
| `classes`, `funcoes` | todo método de `app/` e as funções de `helpers.php`, em IR | `app/**/*.php` |
| `config`, `traducoes`, `middleware`, `politicas` | o que o runtime lê em execução | `config/`, `lang/`, `Http/Kernel`, `Policies` |
| `volateis` | campo de resposta e coluna que mudam a cada execução, **por regra**: data do Eloquent, `Hash::make`, código que lê o relógio | IR |
| `pendencias` | closure em rota, SQL cru, evento/observer, job, pacote de terceiros, nó PHP não lido | tudo acima |

Mesma entrada, mesmos bytes (sem data nem caminho absoluto). `verificar` refaz a extração e diz qual seção
deixou de ser a do fonte.

**2. Gerador** (`gerar.py`, `transpilar.py`). Do contrato, e só dele, sai um projeto FastAPI:
`rotas.py` (uma função por rota, na ordem do Laravel, middleware como `Depends`), `validacoes.py`
(Pydantic de cada FormRequest, no OpenAPI), `modelos.py` (SQLAlchemy `Table` de cada migration),
`app_traduzido.py` (controllers, models, resources, requests, policies traduzidos para Python),
`config_app.py`, `dados.py` e uma cópia do runtime `laravel_compat`. O app não depende deste repositório.

O runtime (`runtime/laravel_compat`) é o pedaço do Laravel 9 que o código traduzido usa: Eloquent sobre
SQLAlchemy Core (gerando o mesmo formato de SQL, para o SQLite devolver as linhas na mesma ordem),
Validator com as mensagens do `lang/` do próprio app, JsonResource com o `wrap` e o 201 do Laravel,
FormRequest, Auth (inclusive guarda customizada via `Auth::extend`), Gate/policies, throttle, Handler de
exceções com os `renderable` do app. A semântica do PHP que o Python não dá igual (`"0"` falso, `==` frouxo,
`.` com null, chave numérica de array) mora em `php.py` com o nome da regra.

`cobertura.json` diz, por rota, se tudo o que ela alcança traduziu sem pendência. É estimativa estática
(fecho por nome); quem diz se responde igual é o passo 3. Trecho sem tradução vira `php.pendencia(...)`:
a rota responde **501** em vez de inventar comportamento.

**3. Avaliador diferencial** (`diferencial.py`, só biblioteca padrão). Os dois apps sobem com cópias
idênticas do mesmo banco semeado (sha256 conferido); cada passo do cenário vai aos dois; compara status,
corpo JSON (normalizando só os voláteis do contrato, e conferindo que uma data tem cara de data) e o banco
inteiro (todas as tabelas, linhas ordenadas). Placar: um endpoint responde igual quando todos os seus
passos bateram; cada diferença sai com o motivo (`corpo $.articles[0].body: ...`, `banco articles: ...`).

    python3 -m laravel_fastapi extrair <app> -o contrato.json
    python3 -m laravel_fastapi verificar contrato.json <app> [--estrito]
    python3 -m laravel_fastapi gerar contrato.json -o gerado/
    python3 -m laravel_fastapi diferencial --cenario c.json --contrato contrato.json \
        --laravel URL,banco.sqlite --fastapi URL,banco.sqlite -o resultado.json

## Caso real: RealWorld ("Conduit") em Laravel 9

[f1amy/laravel-realworld-example-app](https://github.com/f1amy/laravel-realworld-example-app), MIT, commit
`c14fb8370b71a42a3a74b8ea936a1f96b2af9d69` (Laravel v9.17.0, PHP 8.1): a implementação Laravel da
especificação pública RealWorld. 19 rotas REST com JWT caseiro (guarda registrada por `Auth::extend`),
9 FormRequests, 8 resources, 4 models com relações muitos-para-muitos e políticas.

| medido (2026-10-19, factory-01) | resultado |
|---|---|
| contrato | 19 rotas, 10 tabelas / 54 colunas, 4 models / 12 relações, 9 FormRequests, 8 resources, 61 classes, 1 pendência (trait do Sanctum) |
| gerador (estático) | 19 de 19 rotas cobertas |
| esquema SQLAlchemy gerado × banco migrado pelo Laravel | 10 tabelas, 54 colunas, 0 diferença (nome, nulo, chave) |
| **diferencial** | **19 de 19 endpoints respondem igual; 81 de 81 passos** (inclui 422, 401, 403, 404, título com acento, tag repetida, 404 e 405 do framework) |
| controle negativo (um artigo alterado só no banco do FastAPI) | 0 de 19; o avaliador acusou corpo e banco em todos os passos |

Evidência em `casos/realworld/evidencia/`; cenário em `casos/realworld/cenario.json`; semente em
`casos/realworld/semente.sql` (bcrypt com sal fixo, sai igual a cada geração). O JWT do app foi traduzido,
não reescrito: o token do FastAPI tem o mesmo formato do Laravel, inclusive o `exp` igual ao `iat` que o
`Carbon` mutável do app produz.

O que o caso derrubou no caminho (cada um virou regra no runtime ou teste):

- 1ª rodada: 63 de 65 passos. As duas diferenças eram do framework, não do app: rota inexistente no
  Laravel 9.17 responde `{"message": ""}` (não "The route ... could not be found.") e o 405 lista os métodos
  na ordem da rota (`GET, HEAD`), não na do Starlette.
- O cenário tinha um furo (um usuário sem login pedia favorito; os dois lados davam 401): o diferencial
  só prova o que o cenário exercita.
- No Eloquent `$model->tags` é a relação carregada e `$model->tags()` é a consulta: propriedade PHP virou
  `p_<nome>` e leitura de propriedade virou `php.prop(...)`; o PHP ignora argumento a mais, o Python não.

### Receita dos containers (factory-01)

Nada de PHP roda fora de container. Pasta de trabalho própria (`LF_TRABALHO`), containers `lf-*` com
`--cpus 1.5 --memory 4g`, portas só em `127.0.0.1`, sem cofre montado.

    # imagem do Laravel (PHP 8.1 + composer, app no commit fixado)
    FROM php:8.1-cli
    RUN apt-get update && apt-get install -y --no-install-recommends git unzip libzip-dev sqlite3 && docker-php-ext-install zip
    COPY --from=composer:2.8 /usr/bin/composer /usr/bin/composer
    RUN git clone https://github.com/f1amy/laravel-realworld-example-app /app && cd /app \
        && git checkout c14fb8370b71a42a3a74b8ea936a1f96b2af9d69 && composer install --no-dev --no-interaction
    # imagem lf-fastapi:1 = python:3.12-slim + requirements.txt deste app

    docker run --rm -e LF_APP_KEY -e MIGRAR=1 -v <dados>:/dados lf-laravel-rw:c14fb83 sh /entrar.sh   # migra
    LF_TRABALHO=<pasta> bash apps/laravel-fastapi/casos/realworld/rodada.sh                         # uma rodada
    NEGATIVO=1 LF_TRABALHO=<pasta> bash apps/laravel-fastapi/casos/realworld/rodada.sh              # controle

Inversa: `docker rm -f lf-laravel lf-fastapi`, `docker rmi lf-laravel-rw:c14fb83 lf-fastapi:1` e apagar a pasta.
O `throttle:api` do app (60/min) é respeitado com 1,1 s entre passos.

## App grande: BookStack (só contrato e cobertura estática)

[BookStack](https://github.com/BookStackApp/BookStack), MIT, tag v26.09.1, commit
`31d94dd8b98e3334dc01b66bed6d514719a2f85d` (`casos/bookstack.py`, saída em `casos/bookstack/bookstack.json`):

| medido | resultado |
|---|---|
| contrato | 340 rotas (82 da API), 40 tabelas / 278 colunas, 35 models, 502 classes, 2.244 métodos, em ~1 s |
| pendências | 392: 163 comandos de migration fora do `Schema::` (inserts de dados), 89 nós PHP não lidos, 79 pacotes, 40 SQL cru, 20 jobs |
| gerador (estático) | **0 de 82** rotas da API cobertas |

Por que zero, pelos motivos que o próprio gerador lista: toda rota da API passa pelo middleware global de
sessão (`StartSession`, `session()`), e boa parte por `url()`, Flysystem, `DB::raw` e funções de arquivo.
O BookStack não serviu para o diferencial nesta versão por isso; o RealWorld foi escolhido por ser Laravel
idiomático, conhecido, MIT e com especificação de API pública.

## Licenças das dependências (conferidas em 2026-10-19)

| pacote | licença | papel |
|---|---|---|
| tree-sitter 0.26.0 / tree-sitter-php 0.25.1 | MIT / MIT | leitor de PHP (o `nikic/PHP-Parser`, BSD-3, foi descartado: exigiria PHP para ler) |
| fastapi 0.149.0, pydantic 2.14.1, SQLAlchemy 2.1.5 | MIT | app gerado |
| starlette 1.9.0, uvicorn 0.54.0, httpx 0.28.1 | BSD-3-Clause | app gerado e testes |
| bcrypt 5.0.0 | Apache-2.0 | `Hash::make`/`check` compatível com o `$2y$` do PHP |
| regex 2026.9.29 | Apache-2.0 e CNRI-Python | `\pL` das regras `regex:` do Laravel |

## Limites conhecidos (medidos, não supostos)

- O runtime foi escrito com o RealWorld na mesa: cobre o que um app Laravel idiomático usa (Eloquent básico,
  belongsTo/hasMany/belongsToMany, whereHas, FormRequest, Resource, Auth, Gate, throttle). O BookStack mostra
  o que falta para app grande: sessão, `url()`, filesystem, SQL cru, paginação (`paginate()` vira pendência).
- A cobertura estática é por nome (o tipo do receptor é estimado pelas classes já em uso); serve para
  apontar o que falta, não para garantir. O placar vale só para o que o cenário exercita.
- Uma requisição por vez por teste do diferencial; banco SQLite nos dois lados. Postgres/MySQL são o mesmo
  SQLAlchemy, mas não foram medidos aqui.
- Mensagem de framework que muda entre versões do Laravel (404 de rota, 405) está calibrada no 9.17.
