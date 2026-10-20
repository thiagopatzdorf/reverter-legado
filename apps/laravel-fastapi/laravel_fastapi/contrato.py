"""Laravel -> contrato: o que a API nova tem de honrar, em JSON determinístico.

Lê o fonte de um app Laravel (sem rodar PHP) e escreve:

| seção        | o que tem                                                   | de onde vem |
|--------------|-------------------------------------------------------------|-------------|
| `rotas`      | método, caminho, parâmetros, middleware, ação               | RouteServiceProvider + routes/*.php |
| `tabelas`    | colunas, tipos, nulo, único, chave estrangeira              | database/migrations |
| `models`     | tabela, fillable, hidden, casts, relações, escopos          | classes Eloquent |
| `validacoes` | regras de cada FormRequest (literal quando dá)              | app/Http/Requests |
| `recursos`   | wrap, collects e campos de cada JsonResource                | app/Http/Resources |
| `classes`    | todo método de app/ em IR (php.py), para o gerador          | app/**/*.php |
| `config`, `traducoes`, `middleware` | o que o runtime precisa ler        | config/, lang/, Http/Kernel |
| `volateis`   | campos que mudam a cada execução (relógio, sal de hash)     | regra sobre o IR |
| `pendencias` | o que não fecha: closure em rota, SQL cru, evento, job, pacote, nó PHP não lido | tudo acima |

Mesma entrada, mesmos bytes: sem data, sem caminho absoluto, chaves ordenadas.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import php

VERSAO = 1
VERBOS = {"get": ["GET", "HEAD"], "post": ["POST"], "put": ["PUT"], "patch": ["PATCH"],
          "delete": ["DELETE"], "options": ["OPTIONS"], "any": ["GET", "POST", "PUT", "PATCH", "DELETE"]}
ROUTE = "Illuminate\\Support\\Facades\\Route"
SCHEMA = "Illuminate\\Support\\Facades\\Schema"
BASES_MODEL = {"Illuminate\\Database\\Eloquent\\Model", "Illuminate\\Foundation\\Auth\\User"}
BASES_REQUEST = {"Illuminate\\Foundation\\Http\\FormRequest"}
BASES_RESOURCE = {"Illuminate\\Http\\Resources\\Json\\JsonResource", "Illuminate\\Http\\Resources\\Json\\ResourceCollection"}
RELACOES = {"belongsTo", "hasMany", "hasOne", "belongsToMany", "morphTo", "morphMany", "morphOne",
            "morphToMany", "morphedByMany", "hasManyThrough", "hasOneThrough"}
# Chamadas que fogem do que um contrato estático consegue prometer.
SQL_CRU = {"raw", "select", "statement", "unprepared", "whereRaw", "orWhereRaw", "selectRaw", "orderByRaw",
           "havingRaw", "groupByRaw", "fromRaw", "insertGetId"}
EVENTOS = {"event", "broadcast"}
FILAS = {"dispatch", "dispatch_sync", "dispatchSync", "dispatchNow"}
RELOGIO = {("call", "now"), ("call", "time"), ("call", "microtime"), ("call", "date"),
           ("scall", "Illuminate\\Support\\Carbon", "now"), ("scall", "Carbon\\Carbon", "now"),
           ("scall", "Illuminate\\Support\\Str", "random"), ("call", "random_bytes"), ("call", "uniqid")}


# --------------------------------------------------------------------------- utilidades
def _ordenar(valor):
    if isinstance(valor, dict):
        return {k: _ordenar(valor[k]) for k in sorted(valor, key=str)}
    if isinstance(valor, list):
        return [_ordenar(v) for v in valor]
    return valor


def serializar(contrato: dict) -> str:
    return json.dumps(_ordenar(contrato), ensure_ascii=False, indent=1) + "\n"


def nos(ir):
    """Todos os nós de um IR (listas), em profundidade."""
    if isinstance(ir, list):
        if ir and isinstance(ir[0], str):
            yield ir
        for x in ir:
            if isinstance(x, (list, dict)):
                yield from nos(x)
    elif isinstance(ir, dict):
        for v in ir.values():
            yield from nos(v)


def cadeia(ir) -> tuple:
    """`A::x(..)->y(..)->z(..)` vira (raiz, [(x, args), (y, args), (z, args)])."""
    passos = []
    while ir and ir[0] == "mcall":
        passos.append((ir[2], ir[3]))
        ir = ir[1]
    if ir and ir[0] == "scall":
        passos.append((ir[2], ir[3]))
        return ("scall", ir[1]), list(reversed(passos))
    return ir, list(reversed(passos))


def snake(nome: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", nome).lower()


def plural(palavra: str) -> str:
    """Str::plural do Laravel para o inglês comum (o que as tabelas usam)."""
    irregulares = {"person": "people", "man": "men", "child": "children", "foot": "feet", "tooth": "teeth"}
    if palavra in irregulares:
        return irregulares[palavra]
    if re.search(r"[^aeiou]y$", palavra):
        return palavra[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", palavra):
        return palavra + "es"
    return palavra + "s"


def singular(palavra: str) -> str:
    if palavra.endswith("ies"):
        return palavra[:-3] + "y"
    if re.search(r"(ses|xes|zes|ches|shes)$", palavra):
        return palavra[:-2]
    if palavra.endswith("s") and not palavra.endswith("ss"):
        return palavra[:-1]
    return palavra


# --------------------------------------------------------------------------- leitura do projeto
class Projeto:
    def __init__(self, raiz: Path):
        self.raiz = raiz
        self.arquivos: dict[str, dict] = {}
        self.problemas: list[dict] = []
        self.classes: dict[str, dict] = {}
        self.funcoes: dict[str, dict] = {}

    def ler(self, rel: str) -> dict | None:
        if rel in self.arquivos:
            return self.arquivos[rel]
        caminho = self.raiz / rel
        if not caminho.is_file():
            return None
        dados, problemas = php.ler_arquivo(caminho.read_bytes(), rel)
        self.arquivos[rel] = dados
        self.problemas += problemas
        for c in dados["classes"]:
            self.classes[c["nome"]] = c
        if rel.startswith("app/"):
            self.funcoes.update(dados.get("funcoes", {}))
        return dados

    def lista(self, pasta: str) -> list[str]:
        base = self.raiz / pasta
        if not base.is_dir():
            return []
        return sorted(p.relative_to(self.raiz).as_posix() for p in base.rglob("*.php"))

    def ancestrais(self, nome: str) -> list[str]:
        saida, atual = [], self.classes.get(nome)
        while atual and atual.get("pai"):
            saida.append(atual["pai"])
            atual = self.classes.get(atual["pai"])
        return saida

    def herda(self, nome: str, bases: set) -> bool:
        return bool(set(self.ancestrais(nome)) & bases)

    def metodo(self, classe: str, nome: str):
        atual = classe
        while atual:
            c = self.classes.get(atual)
            if not c:
                return None, None
            if nome in c["metodos"]:
                return atual, c["metodos"][nome]
            atual = c.get("pai")
        return None, None

    def propriedade(self, classe: str, nome: str):
        atual = classe
        while atual:
            c = self.classes.get(atual)
            if not c:
                return None
            if nome in c["propriedades"]:
                return c["propriedades"][nome]["valor"]
            atual = c.get("pai")
        return None


def _lit(ir, padrao=None):
    ok, v = php.avaliar_literal(ir)
    return v if ok else padrao


# --------------------------------------------------------------------------- rotas
class LeitorRotas:
    def __init__(self, projeto: Projeto):
        self.p = projeto
        self.rotas: list[dict] = []
        self.pendencias: list[dict] = []

    def caminho_de(self, ir) -> str | None:
        if ir is None:
            return None
        if ir[0] == "call" and ir[1] in ("base_path", "app_path") and ir[2]:
            v = _lit(ir[2][0])
            if isinstance(v, str):
                return ("app/" if ir[1] == "app_path" else "") + v.lstrip("/")
        v = _lit(ir)
        return v if isinstance(v, str) else None

    def arquivo(self, rel: str, ctx: dict) -> None:
        dados = self.p.ler(rel)
        if dados is None:
            self.pendencias.append({"tipo": "arquivo_de_rotas_ausente", "onde": rel})
            return
        self.bloco(dados["topo"], ctx, None, rel)

    def bloco(self, stmts, ctx, classe, arquivo) -> None:
        for s in stmts or []:
            if s[0] == "expr":
                self.expr(s[1], ctx, classe, arquivo)
            elif s[0] in ("if",):
                for _, corpo in s[1]:
                    self.bloco(corpo, ctx, classe, arquivo)

    def expr(self, e, ctx, classe, arquivo) -> None:
        if e[0] == "require":
            rel = self.caminho_de(e[1])
            if rel:
                self.arquivo(rel, ctx)
            return
        if e[0] == "mcall" and e[1] == ["this"] and classe:
            dono, m = self.p.metodo(classe, e[2])
            if m:
                self.bloco(m["corpo"], ctx, classe, arquivo)
            return
        raiz, passos = cadeia(e)
        if raiz == ("scall", ROUTE) or (raiz[0] == "var" and raiz[1] == "router"):
            self.cadeia_route(passos, ctx, classe, arquivo)
            return
        # `$this->routes(function () {...})` e afins: entra nas closures.
        for n in nos(e):
            if n[0] == "closure":
                self.bloco(n[3], ctx, classe, arquivo)
                break

    def _attrs(self, ctx, nome, args) -> dict:
        novo = dict(ctx)
        novo["middleware"] = list(ctx["middleware"])
        valor = _lit(args[0]) if args else None
        if nome == "middleware":
            vals = [_lit(a) for a in args]
            if len(vals) == 1 and isinstance(vals[0], list):
                vals = vals[0]
            novo["middleware"] += [v for v in vals if isinstance(v, str)]
        elif nome == "prefix" and isinstance(valor, str):
            novo["prefixo"] = "/".join(x for x in (ctx["prefixo"].strip("/"), valor.strip("/")) if x)
        elif nome in ("name", "as") and isinstance(valor, str):
            novo["nome"] = ctx["nome"] + valor
        elif nome == "controller":
            novo["controller"] = valor
        elif nome == "namespace" and isinstance(valor, str):
            novo["namespace"] = valor
        elif nome == "domain":
            novo["dominio"] = valor
        return novo

    def cadeia_route(self, passos, ctx, classe, arquivo) -> None:
        atual = ctx
        rota = None
        for nome, args in passos:
            if nome in VERBOS or nome == "match":
                if nome == "match":
                    metodos = [m.upper() for m in (_lit(args[0]) or [])]
                    args = args[1:]
                else:
                    metodos = VERBOS[nome]
                rota = self.nova_rota(metodos, args, atual, arquivo)
            elif nome in ("resource", "apiResource"):
                self.recurso(nome, args, atual, arquivo, passos)
                return
            elif nome == "group":
                if args and args[0][0] == "arr":
                    attrs = _lit(args[0]) or {}
                    for chave in ("middleware", "prefix", "as", "namespace", "controller"):
                        if chave in attrs:
                            v = attrs[chave]
                            atual = self._attrs(atual, chave, [["lit", v]] if not isinstance(v, list) else [["arr", [[None, ["lit", x]] for x in v]]])
                    args = args[1:]
                alvo = args[0] if args else None
                if alvo and alvo[0] in ("closure", "fn"):
                    corpo = alvo[3] if alvo[0] == "closure" else [["expr", alvo[2]]]
                    self.bloco(corpo, atual, classe, arquivo)
                else:
                    rel = self.caminho_de(alvo)
                    if rel:
                        self.arquivo(rel, atual)
            elif rota is not None:
                if nome == "name":
                    rota["nome"] = (rota.get("nome") or "") + (_lit(args[0]) or "")
                elif nome == "middleware":
                    vals = [_lit(a) for a in args]
                    if len(vals) == 1 and isinstance(vals[0], list):
                        vals = vals[0]
                    rota["middleware"] += [v for v in vals if isinstance(v, str)]
                elif nome in ("where", "whereNumber", "whereAlpha", "whereUuid"):
                    rota.setdefault("restricoes", {})
                    if nome == "where" and len(args) == 2:
                        rota["restricoes"][_lit(args[0])] = _lit(args[1])
                    elif args:
                        rota["restricoes"][_lit(args[0])] = nome
                elif nome == "withoutMiddleware":
                    tirar = _lit(args[0])
                    tirar = tirar if isinstance(tirar, list) else [tirar]
                    rota["middleware"] = [m for m in rota["middleware"] if m not in tirar]
            else:
                atual = self._attrs(atual, nome, args)

    def _acao(self, ir, ctx, onde) -> dict:
        if ir is None:
            return {"tipo": "nenhuma"}
        if ir[0] in ("closure", "fn"):
            self.pendencias.append({"tipo": "rota_closure", "onde": onde, "detalhe": "a rota é uma closure, não um controller"})
            return {"tipo": "closure"}
        if ir[0] == "arr":
            v = [x[1] for x in ir[1]]
            if len(v) == 2 and v[0][0] == "classref":
                return {"tipo": "controller", "classe": v[0][1], "metodo": _lit(v[1])}
        if ir[0] == "classref":
            return {"tipo": "controller", "classe": ir[1], "metodo": "__invoke"}
        v = _lit(ir)
        if isinstance(v, str):
            if "@" in v:
                cls, met = v.split("@", 1)
                ns = ctx.get("namespace")
                return {"tipo": "controller", "classe": f"{ns}\\{cls}" if ns and not cls.startswith("\\") else cls.lstrip("\\"), "metodo": met}
            if ctx.get("controller"):
                return {"tipo": "controller", "classe": ctx["controller"], "metodo": v}
        self.pendencias.append({"tipo": "acao_nao_lida", "onde": onde})
        return {"tipo": "desconhecida"}

    def nova_rota(self, metodos, args, ctx, arquivo) -> dict:
        uri = _lit(args[0]) if args else ""
        caminho = "/" + "/".join(x for x in (ctx["prefixo"].strip("/"), str(uri).strip("/")) if x)
        onde = f"{arquivo}:{' '.join(metodos)} {caminho}"
        rota = {
            "metodos": metodos, "caminho": caminho,
            "parametros": [{"nome": m.group(1), "opcional": bool(m.group(2))} for m in re.finditer(r"\{(\w+)(\?)?\}", caminho)],
            "middleware": list(ctx["middleware"]), "nome": ctx["nome"] or None,
            "acao": self._acao(args[1] if len(args) > 1 else None, ctx, onde), "arquivo": arquivo,
        }
        self.rotas.append(rota)
        return rota

    def recurso(self, tipo, args, ctx, arquivo, passos) -> None:
        nome = _lit(args[0])
        ctrl = args[1][1] if len(args) > 1 and args[1][0] == "classref" else None
        acoes = [("index", ["GET", "HEAD"], ""), ("store", ["POST"], ""), ("show", ["GET", "HEAD"], "/{p}"),
                 ("update", ["PUT", "PATCH"], "/{p}"), ("destroy", ["DELETE"], "/{p}")]
        if tipo == "resource":
            acoes[1:1] = [("create", ["GET", "HEAD"], "/create")]
            acoes.insert(4, ("edit", ["GET", "HEAD"], "/{p}/edit"))
        so, exceto = None, set()
        for n, a in passos:
            if n == "only":
                so = set(_lit(a[0]) or [])
            elif n == "except":
                exceto = set(_lit(a[0]) or [])
        param = singular(str(nome).rsplit(".", 1)[-1]).replace("-", "_")
        for acao, metodos, sufixo in acoes:
            if (so is not None and acao not in so) or acao in exceto:
                continue
            uri = str(nome) + sufixo.replace("{p}", "{" + param + "}")
            ir_acao = ["arr", [[None, ["classref", ctrl]], [None, ["lit", acao]]]] if ctrl else None
            r = self.nova_rota(metodos, [["lit", uri], ir_acao], ctx, arquivo)
            r["nome"] = (ctx["nome"] or "") + f"{nome}.{acao}"


def ler_rotas(p: Projeto) -> tuple[list, list]:
    leitor = LeitorRotas(p)
    ctx = {"prefixo": "", "middleware": [], "nome": "", "controller": None, "namespace": None}
    provedor = next((n for n, c in sorted(p.classes.items()) if n.endswith("RouteServiceProvider") and "boot" in c["metodos"]), None)
    if provedor:
        leitor.bloco(p.classes[provedor]["metodos"]["boot"]["corpo"], ctx, provedor, p.classes[provedor]["arquivo"])
    if not leitor.rotas:
        # Laravel 11+: bootstrap/app.php com withRouting(api: ...); sem provedor, convenção.
        for rel, grupo, prefixo in (("routes/api.php", "api", "api"), ("routes/web.php", "web", "")):
            if (p.raiz / rel).is_file():
                leitor.arquivo(rel, {**ctx, "middleware": [grupo], "prefixo": prefixo})
    return leitor.rotas, leitor.pendencias


# --------------------------------------------------------------------------- migrations
TIPOS_COLUNA = {
    "string": "string", "char": "string", "text": "text", "mediumText": "text", "longText": "text", "tinyText": "text",
    "integer": "integer", "tinyInteger": "integer", "smallInteger": "integer", "mediumInteger": "integer",
    "bigInteger": "bigint", "unsignedInteger": "integer", "unsignedTinyInteger": "integer",
    "unsignedSmallInteger": "integer", "unsignedBigInteger": "bigint", "foreignId": "bigint",
    "boolean": "boolean", "date": "date", "dateTime": "datetime", "dateTimeTz": "datetime", "timestamp": "datetime",
    "timestampTz": "datetime", "time": "time", "json": "json", "jsonb": "json", "decimal": "decimal",
    "float": "float", "double": "float", "uuid": "string", "foreignUuid": "string", "ulid": "string",
    "enum": "string", "binary": "binary", "year": "integer", "ipAddress": "string", "macAddress": "string",
}


def _coluna(nome, tipo, **extra) -> dict:
    c = {"nome": nome, "tipo": tipo, "nulo": False}
    c.update(extra)
    return c


def ler_migrations(p: Projeto) -> tuple[dict, list]:
    tabelas: dict[str, dict] = {}
    pendencias = []
    for rel in p.lista("database/migrations"):
        dados = p.ler(rel)
        classes = [c for c in dados["classes"]] + [n[1] for n in nos(dados.get("retorno")) if n[0] == "anonclass"]
        for c in classes:
            up = c["metodos"].get("up")
            if not up:
                continue
            for s in up["corpo"] or []:
                if s[0] != "expr":
                    pendencias.append({"tipo": "migration_nao_lida", "onde": f"{rel}:{up['linha']}"})
                    continue
                raiz, passos = cadeia(s[1])
                if raiz != ("scall", SCHEMA) or not passos:
                    pendencias.append({"tipo": "migration_nao_lida", "onde": f"{rel}:{up['linha']}", "detalhe": "comando fora do Schema::"})
                    continue
                acao, args = passos[0]
                nome_t = _lit(args[0]) if args else None
                if acao in ("create", "table") and len(args) > 1 and args[1][0] in ("closure", "fn"):
                    t = tabelas.setdefault(nome_t, {"colunas": [], "unicos": [], "primaria": None, "origem": rel})
                    if acao == "create":
                        t.update({"colunas": [], "unicos": [], "primaria": None, "origem": rel})
                    var = args[1][1][0]["nome"] if args[1][1] else "table"
                    corpo = args[1][3] if args[1][0] == "closure" else [["expr", args[1][2]]]
                    for cs in corpo:
                        if cs[0] != "expr":
                            continue
                        if not _blueprint(t, cs[1], var):
                            pendencias.append({"tipo": "migration_nao_lida", "onde": f"{rel}:{nome_t}", "detalhe": json.dumps(cs[1])[:120]})
                elif acao in ("drop", "dropIfExists"):
                    tabelas.pop(nome_t, None)
                elif acao == "rename" and len(args) == 2:
                    tabelas[_lit(args[1])] = tabelas.pop(nome_t, {})
                else:
                    pendencias.append({"tipo": "migration_nao_lida", "onde": f"{rel}:{acao}"})
    return tabelas, pendencias


def _blueprint(t: dict, e, var: str) -> bool:
    raiz, passos = cadeia(e)
    if raiz != ["var", var] or not passos:
        return False
    nome, args = passos[0]
    vals = [_lit(a) for a in args]
    cols = t["colunas"]

    def achar(n):
        return next((c for c in cols if c["nome"] == n), None)

    novas: list[dict] = []
    if nome in ("id", "bigIncrements", "increments"):
        novas.append(_coluna(vals[0] if vals else "id", "bigint" if nome != "increments" else "integer", primaria=True, auto=True))
    elif nome == "timestamps" or nome == "nullableTimestamps":
        novas += [_coluna("created_at", "datetime", nulo=True), _coluna("updated_at", "datetime", nulo=True)]
    elif nome == "softDeletes":
        novas.append(_coluna(vals[0] if vals else "deleted_at", "datetime", nulo=True))
    elif nome == "rememberToken":
        novas.append(_coluna("remember_token", "string", nulo=True, tamanho=100))
    elif nome in ("morphs", "nullableMorphs"):
        base = vals[0]
        novas += [_coluna(f"{base}_type", "string", nulo=nome.startswith("nullable")),
                  _coluna(f"{base}_id", "bigint", nulo=nome.startswith("nullable"))]
    elif nome in TIPOS_COLUNA:
        extra = {}
        if nome in ("string", "char") and len(vals) > 1 and isinstance(vals[1], int):
            extra["tamanho"] = vals[1]
        elif nome in ("string", "char"):
            extra["tamanho"] = 255
        if nome == "enum" and len(vals) > 1:
            extra["valores"] = vals[1]
        novas.append(_coluna(vals[0], TIPOS_COLUNA[nome], **extra))
    elif nome == "unique" and vals and isinstance(vals[0], list):
        t["unicos"].append(vals[0])
        return True
    elif nome == "primary":
        t["primaria"] = vals[0] if isinstance(vals[0], list) else [vals[0]]
        return True
    elif nome in ("index", "fullText", "spatialIndex"):
        return True
    elif nome == "foreign":
        col = achar(vals[0])
        ref = {}
        for n2, a2 in passos[1:]:
            v2 = _lit(a2[0]) if a2 else None
            if n2 == "references":
                ref["coluna"] = v2
            elif n2 == "on":
                ref["tabela"] = v2
            elif n2 in ("onDelete", "cascadeOnDelete"):
                ref["ao_apagar"] = v2 or "cascade"
        if col is not None:
            col["ref"] = ref
        return col is not None
    elif nome == "dropColumn":
        alvo = vals[0] if isinstance(vals[0], list) else vals
        t["colunas"] = [c for c in cols if c["nome"] not in alvo]
        return True
    elif nome == "renameColumn":
        col = achar(vals[0])
        if col:
            col["nome"] = vals[1]
        return col is not None
    else:
        return False
    for col in novas:
        for n2, a2 in passos[1:]:
            v2 = _lit(a2[0]) if a2 else None
            if n2 == "nullable":
                col["nulo"] = v2 is not False
            elif n2 == "unique":
                t["unicos"].append([col["nome"]])
            elif n2 == "default":
                col["padrao"] = v2
            elif n2 == "unsigned":
                col["sem_sinal"] = True
            elif n2 == "primary":
                col["primaria"] = True
            elif n2 in ("constrained",):
                tabela_ref = v2 or plural(col["nome"].removesuffix("_id"))
                col["ref"] = {"tabela": tabela_ref, "coluna": "id"}
            elif n2 in ("onDelete", "cascadeOnDelete", "nullOnDelete", "restrictOnDelete"):
                col.setdefault("ref", {})["ao_apagar"] = {"cascadeOnDelete": "cascade", "nullOnDelete": "set null",
                                                          "restrictOnDelete": "restrict"}.get(n2, v2)
            elif n2 == "change":
                velha = achar(col["nome"])
                if velha:
                    cols.remove(velha)
        if nome == "foreignId" or nome == "foreignUuid":
            col["sem_sinal"] = True
        existente = achar(col["nome"])
        if existente:
            cols.remove(existente)
        cols.append(col)
    return True


# --------------------------------------------------------------------------- models, requests, resources
def ler_models(p: Projeto) -> dict:
    saida = {}
    for nome, c in sorted(p.classes.items()):
        if not p.herda(nome, BASES_MODEL) or c["abstrata"]:
            continue
        curto = nome.rsplit("\\", 1)[-1]
        relacoes, escopos, metodos = [], [], []
        for m_nome, m in sorted(c["metodos"].items()):
            corpo = m["corpo"] or []
            if m_nome.startswith("scope") and len(m_nome) > 5:
                escopos.append(m_nome[5].lower() + m_nome[6:])
                continue
            if len(corpo) == 1 and corpo[0][0] == "return":
                raiz, passos = cadeia(corpo[0][1])
                if raiz == ["this"] and passos and passos[0][0] in RELACOES:
                    tipo, args = passos[0]
                    relacoes.append({"nome": m_nome, "tipo": tipo, "alvo": args[0][1] if args and args[0][0] == "classref" else None,
                                     "args": [_lit(a) for a in args[1:]], "extra": [n for n, _ in passos[1:]]})
                    continue
            metodos.append(m_nome)
        tabela = _lit(p.propriedade(nome, "table")) or plural(snake(curto))
        saida[nome] = {
            "tabela": tabela, "fillable": _lit(p.propriedade(nome, "fillable")) or [],
            "guarded": _lit(p.propriedade(nome, "guarded"), ["*"]) if p.propriedade(nome, "guarded") else None,
            "hidden": _lit(p.propriedade(nome, "hidden")) or [], "casts": _lit(p.propriedade(nome, "casts")) or {},
            "chave": _lit(p.propriedade(nome, "primaryKey")) or "id",
            "timestamps": _lit(p.propriedade(nome, "timestamps"), True) is not False,
            "relacoes": relacoes, "escopos": escopos, "metodos": metodos, "arquivo": c["arquivo"],
        }
        if saida[nome]["guarded"] is None:
            del saida[nome]["guarded"]
    return saida


def _regras_estaticas(p: Projeto, nome: str):
    _, m = p.metodo(nome, "rules")
    if not m or not m["corpo"] or m["corpo"][-1][0] != "return":
        return None
    ok, v = php.avaliar_literal(m["corpo"][-1][1])
    if not ok:
        return None
    return {k: (r.split("|") if isinstance(r, str) else r) for k, r in v.items()}


def ler_validacoes(p: Projeto) -> dict:
    saida = {}
    for nome, c in sorted(p.classes.items()):
        if not p.herda(nome, BASES_REQUEST):
            continue
        dados = None
        _, vd = p.metodo(nome, "validationData")
        if vd and vd["corpo"]:
            for n in nos(vd["corpo"]):
                if n[0] == "mcall" and n[1] == ["this"] and n[2] == "input" and n[3]:
                    dados = _lit(n[3][0])
        dono_regras, _ = p.metodo(nome, "rules")
        saida[nome] = {
            "abstrata": c["abstrata"], "regras": _regras_estaticas(p, nome),
            "regras_de": dono_regras, "dados_em": dados,
            "prepara": p.metodo(nome, "prepareForValidation")[1] is not None,
            "autoriza": p.metodo(nome, "authorize")[1] is not None, "arquivo": c["arquivo"],
        }
    return saida


def ler_recursos(p: Projeto) -> dict:
    saida = {}
    for nome, c in sorted(p.classes.items()):
        if not p.herda(nome, BASES_RESOURCE) or c["abstrata"]:
            continue
        campos = []
        atual = nome
        while atual and atual in p.classes:
            m = p.classes[atual]["metodos"].get("toArray")
            if m and m["corpo"]:
                for n in nos(m["corpo"]):
                    if n[0] == "arr":
                        campos += [_lit(it[0]) for it in n[1] if it[0] is not None and isinstance(_lit(it[0]), str)]
                        break
            atual = p.classes[atual].get("pai")
        colecao = "Illuminate\\Http\\Resources\\Json\\ResourceCollection" in p.ancestrais(nome)
        collects = p.propriedade(nome, "collects")
        saida[nome] = {
            "wrap": _lit(p.propriedade(nome, "wrap"), "data") if p.propriedade(nome, "wrap") else "data",
            "colecao": colecao, "collects": collects[1] if collects and collects[0] == "classref" else None,
            "campos": sorted(set(campos)), "arquivo": c["arquivo"],
        }
    return saida


# --------------------------------------------------------------------------- pendências e voláteis
def pendencias_de_codigo(p: Projeto, models: dict) -> list:
    saida = []
    for nome, c in sorted(p.classes.items()):
        if c["arquivo"].startswith("database/"):
            continue
        for m_nome, m in sorted(c["metodos"].items()):
            onde = f"{c['arquivo']}:{m['linha']} {nome.rsplit(chr(92), 1)[-1]}::{m_nome}"
            for n in nos(m["corpo"]):
                if n[0] == "scall" and n[1] == "Illuminate\\Support\\Facades\\DB" and n[2] in SQL_CRU | {"table"}:
                    saida.append({"tipo": "sql_cru", "onde": onde, "detalhe": f"DB::{n[2]}"})
                elif n[0] == "mcall" and n[2] in SQL_CRU and n[2] not in ("select",):
                    saida.append({"tipo": "sql_cru", "onde": onde, "detalhe": f"->{n[2]}()"})
                elif (n[0] == "call" and n[1] in EVENTOS) or (n[0] == "scall" and n[1].endswith("Facades\\Event")):
                    saida.append({"tipo": "evento", "onde": onde, "detalhe": n[1] if n[0] == "call" else "Event::" + n[2]})
                elif (n[0] == "call" and n[1] in FILAS) or (n[0] == "scall" and n[2] in FILAS and n[1] in p.classes):
                    saida.append({"tipo": "job", "onde": onde, "detalhe": n[1] if n[0] == "call" else n[1].rsplit("\\", 1)[-1] + "::" + n[2]})
                elif n[0] == "scall" and n[2] == "observe":
                    saida.append({"tipo": "observer", "onde": onde, "detalhe": n[1].rsplit("\\", 1)[-1] + "::observe"})
        if "Illuminate\\Contracts\\Queue\\ShouldQueue" in c["interfaces"]:
            saida.append({"tipo": "job", "onde": c["arquivo"], "detalhe": "ShouldQueue"})
        if nome in models and p.propriedade(nome, "dispatchesEvents"):
            saida.append({"tipo": "evento", "onde": c["arquivo"], "detalhe": "$dispatchesEvents"})
    return saida


def pacotes_externos(p: Projeto) -> list:
    """Classes citadas que não são do app nem do Laravel: dependência de pacote."""
    citadas = set()
    for c in p.classes.values():
        for n in nos([c["metodos"], c["propriedades"], c["pai"] or "", c["tracos"]]):
            if n[0] in ("scall", "new", "classref", "cconst", "sprop"):
                citadas.add(n[1])
        for x in [c["pai"], *c["tracos"], *c["interfaces"]]:
            if x:
                citadas.add(x)
    externas = sorted(x for x in citadas if "\\" in x and x not in p.classes and not x.startswith(("Illuminate\\", "Symfony\\")))
    return [{"tipo": "pacote", "onde": x, "detalhe": x.split("\\", 1)[0]} for x in externas]


def volateis(p: Projeto, tabelas: dict) -> dict:
    """Campos que mudam a cada execução, pela regra, não por lista à mão.

    - coluna de data que o Eloquent preenche (`timestamps()`): created_at/updated_at;
    - coluna gravada com `Hash::make` (sal aleatório);
    - campo de resposta cujo valor sai de código que lê o relógio ou sorteia (`now()`,
      `Carbon::now`, `Str::random`), seguindo as chamadas estáticas até 3 níveis.
    """
    colunas = set()
    for t in tabelas.values():
        for c in t["colunas"]:
            if c["nome"] in ("created_at", "updated_at", "remember_token"):
                colunas.add(c["nome"])
    for c in p.classes.values():
        for n in nos(c["metodos"]):
            if n[0] == "assign" and n[1][0] == "idx" and n[2][0] == "scall" and n[2][1].endswith("Facades\\Hash"):
                colunas.add(_lit(n[1][2]))
    colunas.discard(None)

    def toca_relogio(classe, metodo, prof=0) -> bool:
        if prof > 3:
            return False
        _, m = p.metodo(classe, metodo)
        if not m:
            return False
        for n in nos(m["corpo"]):
            if n[0] == "call" and (n[0], n[1]) in RELOGIO:
                return True
            if n[0] == "scall" and isinstance(n[1], str) and (n[0], n[1], n[2]) in RELOGIO:
                return True
            if n[0] == "scall" and isinstance(n[1], str) and n[1] in p.classes and toca_relogio(n[1], n[2], prof + 1):
                return True
        return False

    campos = set()
    for nome, c in p.classes.items():
        if not p.herda(nome, BASES_RESOURCE):
            continue
        m = c["metodos"].get("toArray")
        for n in nos(m["corpo"] if m else []):
            if n[0] != "arr":
                continue
            for it in n[1]:
                chave = _lit(it[0]) if it[0] else None
                if not isinstance(chave, str):
                    continue
                v = it[1]
                if v[0] == "prop" and v[2] in colunas:
                    campos.add(chave)
                elif any(x[0] == "scall" and isinstance(x[1], str) and x[1] in p.classes and toca_relogio(x[1], x[2]) for x in nos(v)):
                    campos.add(chave)
    return {"colunas": sorted(colunas), "resposta": sorted(campos)}


# --------------------------------------------------------------------------- montagem
def _versao_laravel(raiz: Path) -> str | None:
    lock = raiz / "composer.lock"
    if not lock.is_file():
        return None
    for pacote in json.loads(lock.read_text(encoding="utf-8")).get("packages", []):
        if pacote["name"] == "laravel/framework":
            return pacote["version"]
    return None


def _literal_de_arquivo(p: Projeto, rel: str):
    dados = p.ler(rel)
    return _lit(dados["retorno"]) if dados else None


def extrair(raiz: Path) -> dict:
    raiz = Path(raiz)
    p = Projeto(raiz)
    for rel in p.lista("app"):
        p.ler(rel)
    rotas, pend_rotas = ler_rotas(p)
    tabelas, pend_mig = ler_migrations(p)
    models = ler_models(p)
    kernel = next((c for n, c in sorted(p.classes.items()) if n.endswith("Http\\Kernel")), None)
    middleware = {}
    if kernel:
        for chave, prop in (("global", "middleware"), ("grupos", "middlewareGroups"),
                            ("apelidos", "routeMiddleware"), ("apelidos", "middlewareAliases")):
            v = kernel["propriedades"].get(prop)
            if v:
                middleware[chave] = _lit(v["valor"]) or middleware.get(chave)
    config = {}
    for rel in p.lista("config"):
        dados = p.ler(rel)
        config[Path(rel).stem] = dados["retorno"]
    traducoes = {}
    for pasta in ("lang/en", "resources/lang/en"):
        for rel in p.lista(pasta):
            v = _literal_de_arquivo(p, rel)
            if isinstance(v, dict):
                traducoes[Path(rel).stem] = v
    pendencias = pend_rotas + pend_mig + pendencias_de_codigo(p, models) + pacotes_externos(p)
    for pr in p.problemas:
        if not pr["arquivo"].startswith(("config/", "database/", "lang/", "resources/")):
            pendencias.append({"tipo": "php_nao_lido", "onde": f"{pr['arquivo']}:{pr['linha']}", "detalhe": pr["tipo"]})
    classes = {n: c for n, c in p.classes.items() if c["arquivo"].startswith("app/")}
    politicas = {}
    for n in classes:
        if "\\Policies\\" in n and n.endswith("Policy"):
            modelo = next((m for m in models if m.rsplit("\\", 1)[-1] == n.rsplit("\\", 1)[-1][:-6]), None)
            if modelo:
                politicas[modelo] = n
    acoes_ok = [r for r in rotas if r["acao"]["tipo"] == "controller"]
    contrato = {
        "versao": VERSAO,
        "laravel": _versao_laravel(raiz),
        "rotas": rotas,
        "tabelas": tabelas,
        "models": models,
        "validacoes": ler_validacoes(p),
        "recursos": ler_recursos(p),
        "politicas": politicas,
        "middleware": middleware,
        "config": config,
        "traducoes": traducoes,
        "classes": classes,
        "funcoes": p.funcoes,
        "volateis": volateis(p, tabelas),
        "pendencias": sorted(pendencias, key=lambda x: (x["tipo"], x["onde"], x.get("detalhe", ""))),
    }
    contrato["cobertura"] = {
        "rotas": len(rotas), "rotas_com_controller": len(acoes_ok),
        "controllers": len({r["acao"]["classe"] for r in acoes_ok}),
        "tabelas": len(tabelas), "colunas": sum(len(t["colunas"]) for t in tabelas.values()),
        "models": len(models), "relacoes": sum(len(m["relacoes"]) for m in models.values()),
        "form_requests": len(contrato["validacoes"]), "recursos": len(contrato["recursos"]),
        "classes": len(classes), "metodos": sum(len(c["metodos"]) for c in classes.values()),
        "funcoes_globais": len(p.funcoes),
        "pendencias": len(pendencias),
        "pendencias_por_tipo": {t: sum(1 for x in pendencias if x["tipo"] == t) for t in sorted({x["tipo"] for x in pendencias})},
    }
    return contrato


SECOES = ("rotas", "tabelas", "models", "validacoes", "recursos", "politicas", "middleware", "config",
          "traducoes", "classes", "funcoes", "volateis", "pendencias", "cobertura")


def verificar(contrato: dict, raiz: Path, estrito: bool = False) -> list[str]:
    """O avaliador barato: refaz a extração e diz, por seção, o que deixou de bater."""
    novo = json.loads(serializar(extrair(raiz)))
    velho = json.loads(serializar(contrato))
    erros = [f"seção {s} difere do fonte" for s in SECOES if novo.get(s) != velho.get(s)]
    if velho.get("versao") != VERSAO:
        erros.append(f"versão do contrato {velho.get('versao')} != {VERSAO}")
    if estrito and novo["pendencias"]:
        erros.append(f"{len(novo['pendencias'])} pendências abertas")
    return erros
