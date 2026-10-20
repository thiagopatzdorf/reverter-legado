"""Delphi -> contrato: o que o sistema novo tem de honrar, em JSON determinístico.

O contrato não traduz código. Ele lista o que o legado promete ao usuário e ao
banco: telas e seus eventos, regras com assinatura, SQL com tabelas e
parâmetros, e as operações que ligam um clique a um SQL. Cada item aponta para
arquivo e linha, e o que não fecha vira pendência explícita.

Mesma entrada, mesmos bytes: sem data, sem caminho absoluto, listas ordenadas.
É isso que permite ao `verificar` dizer se o contrato ainda é o do fonte.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import dfm, pascal

VERSAO = 1
EXTENSOES = {".pas", ".dpr", ".dpk", ".dfm"}
# Pastas que o IDE cria sozinho: cópias velhas do mesmo fonte, não contrato.
IGNORAR = {"__history", "__recovery", "backup", ".git"}
# Geometria e aparência não são contrato: o sistema novo desenha a tela do jeito dele.
LAYOUT = {
    "Left", "Top", "Width", "Height", "TabOrder", "TabStop", "ClientHeight", "ClientWidth",
    "PixelsPerInch", "TextHeight", "OldCreateOrder", "Ctl3D", "ParentFont", "ParentColor",
    "Color", "Anchors", "Align", "Position", "Scaled", "DesignSize", "Visible", "BorderStyle",
    "ParentBackground", "ParentCtl3D", "ImeName", "ImeMode", "AutoSize", "Transparent",
}
LAYOUT_PREFIXOS = ("Font.", "Explicit", "Margins.", "Padding.", "Constraints.", "Glyph.", "Picture.", "Icon.")
PROPS_SQL = ("SQL", "SQL.Strings", "CommandText", "SelectSQL.Strings", "InsertSQL.Strings",
             "ModifySQL.Strings", "DeleteSQL.Strings", "RefreshSQL.Strings")


def _json(valor):
    if isinstance(valor, dfm.Binario):
        return {"binario_bytes": len(valor)}
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_json(v) for v in valor]
    if isinstance(valor, str):
        return str(valor)
    return valor


def _eh_layout(prop: str) -> bool:
    return prop in LAYOUT or prop.startswith(LAYOUT_PREFIXOS)


def arquivos(raiz: Path) -> list[Path]:
    saida = []
    for p in raiz.rglob("*"):
        rel = p.relative_to(raiz)
        if p.is_file() and p.suffix.lower() in EXTENSOES and not (set(rel.parts[:-1]) & IGNORAR):
            saida.append(p)
    return sorted(saida, key=lambda p: p.relative_to(raiz).as_posix().lower())


def _texto_fonte(dados: bytes) -> str:
    for cod in ("utf-8-sig", "cp1252"):
        try:
            return dados.decode(cod)
        except UnicodeDecodeError:
            continue
    return dados.decode("latin-1")


def _componentes(no: dict, pai: str | None, saida: list) -> None:
    for filho in no["filhos"]:
        props = {k: _json(v) for k, v in filho["propriedades"].items() if not _eh_layout(k) and not k.startswith("On")}
        item = {"nome": filho["nome"], "classe": filho["classe"], "pai": pai}
        if props:
            item["propriedades"] = props
        saida.append(item)
        _componentes(filho, filho["nome"], saida)


def _eventos(no: dict, saida: list) -> None:
    for prop, valor in sorted(no["propriedades"].items()):
        if prop.startswith("On") and isinstance(valor, dfm.Ident):
            saida.append({"componente": no["nome"], "evento": prop, "handler": str(valor)})
    for filho in no["filhos"]:
        _eventos(filho, saida)


def _sql_do_dfm(no: dict, arquivo: str, saida: list) -> None:
    for prop in PROPS_SQL:
        valor = no["propriedades"].get(prop)
        if valor:
            texto = " ".join(valor) if isinstance(valor, list) else str(valor)
            if texto.strip():
                s = pascal.descrever_sql(texto, f"{arquivo}:{no['nome']}.{prop}")
                s["componente"] = no["nome"]
                saida.append(s)
    tabela = no["propriedades"].get("TableName")
    if isinstance(tabela, str) and tabela:
        saida.append({
            "origem": f"{arquivo}:{no['nome']}.TableName", "operacao": "TABELA", "texto": "",
            "tabelas": [tabela.upper()], "parametros": [], "componente": no["nome"],
        })
    for filho in no["filhos"]:
        _sql_do_dfm(filho, arquivo, saida)


def formulario(rel: str, arvore: dict, unidade: str | None) -> dict:
    """Uma tela no contrato. Quem chama decide `implementado` de cada evento:
    pelo corpo da rotina (fonte) ou pela tabela de métodos publicados (executável)."""
    componentes, eventos = [], []
    _componentes(arvore, None, componentes)
    _eventos(arvore, eventos)
    for e in eventos:
        e["rotina"] = f"{arvore['classe']}.{e['handler']}"
    props = {k: _json(v) for k, v in arvore["propriedades"].items() if not _eh_layout(k) and not k.startswith("On")}
    return {
        "nome": arvore["nome"], "classe": arvore["classe"], "arquivo": rel, "unidade": unidade,
        "propriedades": props, "componentes": componentes, "eventos": eventos,
    }


def do_projeto(dpr: Path) -> tuple[Path, list[Path], list[str]]:
    """As units que o .dpr declara (`uses X in '..\\src\\x.pas'`), o .dfm de cada uma e o próprio .dpr.

    É o mesmo recorte do compilador: pasta de projeto real mistura demos e
    bibliotecas de terceiros (no HeidiSQL, telas de exemplo do Detours e do
    SizeGrip entravam no contrato como se fossem do sistema).
    """
    dpr = dpr.resolve()
    unidade = pascal.ler_unidade(_texto_fonte(dpr.read_bytes()), dpr.name)
    lista, faltando = [dpr], []
    for u in unidade["usa"]:
        if "arquivo" not in u:
            continue  # unit de biblioteca (Forms, SysUtils): achada pelo caminho de busca, não é do projeto
        pas = (dpr.parent / u["arquivo"].replace("\\", "/")).resolve()
        if not pas.is_file():
            faltando.append(u["arquivo"])
            continue
        lista.append(pas)
        dfm_ = next((c for c in pas.parent.glob(pas.stem + ".*") if c.suffix.lower() == ".dfm"), None)
        if dfm_:
            lista.append(dfm_)
    base = Path(os.path.commonpath([str(p.parent) for p in lista]))
    return base, sorted(set(lista), key=lambda p: p.relative_to(base).as_posix().lower()), faltando


def extrair(raiz: Path) -> dict:
    """Pasta -> contrato pelo fonte; .dpr/.dpk -> só as units do projeto;
    .exe/.dll/.bpl -> contrato pelo binário."""
    raiz = Path(raiz)
    faltando: list[str] = []
    if raiz.is_file() and raiz.suffix.lower() in (".dpr", ".dpk"):
        raiz, lista, faltando = do_projeto(raiz)
    elif raiz.is_file():
        from . import binario
        return binario.extrair(raiz)
    else:
        lista = arquivos(raiz)
    origem, unidades, formularios, sql, pendencias = [], [], [], [], []
    for caminho in faltando:
        pendencias.append({"tipo": "unit_ausente", "onde": caminho, "detalhe": "declarada no projeto, arquivo não encontrado"})
    for caminho in lista:
        rel = caminho.relative_to(raiz).as_posix()
        dados = caminho.read_bytes()
        origem.append({"caminho": rel, "sha256": hashlib.sha256(dados).hexdigest()})
        if caminho.suffix.lower() == ".dfm":
            try:
                arvore = dfm.ler(dados)
            except dfm.DfmInvalido as erro:
                pendencias.append({"tipo": "arquivo_ilegivel", "onde": rel, "detalhe": str(erro)})
                continue
            formularios.append((rel, arvore))
            _sql_do_dfm(arvore, rel, sql)
        else:
            u = pascal.ler_unidade(_texto_fonte(dados), rel)
            unidades.append(u)
            sql += u["sql"]

    implementadas = {n.lower() for u in unidades for n in u["implementadas"]}
    classes = {}
    for u in unidades:
        for c in u["classes"]:
            classes[c["nome"].lower()] = (u, c)

    contrato_forms = []
    for rel, arvore in formularios:
        dono = classes.get(arvore["classe"].lower())
        if dono is None:
            pendencias.append({"tipo": "formulario_sem_unidade", "onde": rel,
                               "detalhe": f"classe {arvore['classe']} não declarada em nenhuma unit lida"})
        form = formulario(rel, arvore, dono[0]["nome"] if dono else None)
        declarados = {m["nome"].lower() for m in dono[1]["metodos"]} if dono else set()
        for e in form["eventos"]:
            e["implementado"] = e["rotina"].lower() in implementadas
            if not e["implementado"]:
                motivo = "declarado na classe, sem corpo" if e["handler"].lower() in declarados else "não declarado"
                pendencias.append({"tipo": "evento_sem_implementacao", "onde": f"{rel}:{e['componente']}.{e['evento']}",
                                   "detalhe": f"{e['rotina']} ({motivo})"})
        contrato_forms.append(form)

    for u in unidades:
        for c in u["classes"]:
            for m in c["metodos"]:
                if "abstract" in m.get("diretivas", []):
                    continue
                if f"{c['nome']}.{m['nome']}".lower() not in implementadas:
                    pendencias.append({"tipo": "metodo_sem_corpo", "onde": u["arquivo"], "detalhe": f"{c['nome']}.{m['nome']}"})
        for r in u["rotinas"]:
            if "external" not in r.get("diretivas", []) and r["nome"].lower() not in implementadas:
                pendencias.append({"tipo": "rotina_sem_corpo", "onde": u["arquivo"], "detalhe": r["nome"]})
    for s in sql:
        if s.get("dinamico"):
            pendencias.append({"tipo": "sql_dinamico", "onde": s["origem"],
                               "detalhe": "parte do SQL vem de variável; a tabela real só aparece em execução"})

    corpos = {nome.lower(): (nome, alc) for u in unidades for nome, alc in u["corpos"].items()}
    por_nome_curto: dict[str, list[str]] = {}
    for chave in corpos:
        por_nome_curto.setdefault(chave.rsplit(".", 1)[-1], []).append(chave)

    def alcance(rotina: str) -> tuple[list[str], set[str]]:
        """Rotinas alcançadas a partir do evento (por nome, transitivo) e datasets abertos."""
        vistos, fila, abre = [], [rotina.lower()], set()
        while fila:
            atual = fila.pop(0)
            if atual in vistos or atual not in corpos:
                continue
            vistos.append(atual)
            _, alc = corpos[atual]
            abre |= {a.lower() for a in alc["abre"]}
            for ident in alc["ids"]:
                fila += [c for c in por_nome_curto.get(ident, []) if c not in vistos]
        return [corpos[v][0] for v in vistos], abre

    operacoes = []
    for f in contrato_forms:
        for e in f["eventos"]:
            rotinas, abre = alcance(e["rotina"])
            alvo = {r.lower() for r in rotinas}
            daqui = [s for s in sql if s.get("rotina", "").lower() in alvo or s.get("componente", "").lower() in abre]
            operacoes.append({
                "id": f"{f['nome']}.{e['componente']}.{e['evento']}",
                "formulario": f["nome"], "gatilho": f"{e['componente']}.{e['evento']}", "rotina": e["rotina"],
                "implementado": e["implementado"], "chama": sorted(rotinas[1:]),
                "sql": sorted(s["origem"] for s in daqui),
                "tabelas": sorted({t for s in daqui for t in s["tabelas"]}),
                "parametros": sorted({p for s in daqui for p in s["parametros"]}),
            })

    tabelas: dict[str, list[str]] = {}
    for s in sql:
        for t in s["tabelas"]:
            tabelas.setdefault(t, []).append(s["origem"])

    contrato = {
        "versao": VERSAO,
        "origem": {"tipo": "fonte", "arquivos": origem},
        "unidades": [
            {
                "nome": u["nome"], "arquivo": u["arquivo"], "tipo": u["tipo"],
                "usa": sorted({x["unidade"] for x in u["usa"]}, key=str.lower),
                "rotinas": u["rotinas"], "registros": u["registros"], "enumeracoes": u["enumeracoes"],
                "interfaces": u["interfaces"],
                "campos_lidos": u["campos_lidos"],
            }
            for u in unidades
        ],
        "classes": [dict(c, unidade=u["nome"]) for u in unidades for c in u["classes"]],
        "formularios": contrato_forms,
        "sql": sorted(sql, key=lambda s: s["origem"]),
        "tabelas": {t: sorted(set(o)) for t, o in sorted(tabelas.items())},
        "operacoes": sorted(operacoes, key=lambda o: o["id"]),
        "pendencias": sorted(pendencias, key=lambda p: (p["tipo"], p["onde"], p["detalhe"])),
    }
    contrato["cobertura"] = {
        "arquivos": len(origem), "unidades": len(unidades), "formularios": len(contrato_forms),
        "componentes": sum(len(f["componentes"]) for f in contrato_forms),
        "eventos": sum(len(f["eventos"]) for f in contrato_forms),
        "eventos_implementados": sum(e["implementado"] for f in contrato_forms for e in f["eventos"]),
        "sql": len(sql), "tabelas": len(tabelas), "operacoes": len(operacoes), "pendencias": len(pendencias),
    }
    return contrato


def serializar(contrato: dict) -> str:
    return json.dumps(contrato, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def verificar(contrato: dict, raiz: Path, *, estrito: bool = False) -> list[str]:
    """Problemas do contrato contra o fonte. Vazio = o contrato é o do fonte.

    É o avaliador barato: refaz a extração e compara. Contrato editado à mão ou
    fonte que mudou depois aparecem aqui, com a seção que divergiu.
    """
    problemas = []
    for chave in ("versao", "origem", "unidades", "formularios", "sql", "operacoes", "pendencias", "cobertura"):
        if chave not in contrato:
            problemas.append(f"falta a seção '{chave}'")
    if contrato.get("versao") != VERSAO:
        problemas.append(f"versão {contrato.get('versao')!r}; este extrator gera {VERSAO}")
    if problemas:
        return problemas
    novo = json.loads(serializar(extrair(raiz)))
    for chave in sorted(set(novo) | set(contrato)):
        if novo.get(chave) != contrato.get(chave):
            problemas.append(f"seção '{chave}' diverge do fonte (rode extrair de novo ou desfaça a edição)")
    if estrito and contrato["pendencias"]:
        problemas.append(f"{len(contrato['pendencias'])} pendência(s) em aberto (--estrito)")
    return problemas


def relatorio(contrato: dict) -> str:
    """O contrato em prosa, para quem decide a migração ler sem abrir JSON."""
    c = contrato["cobertura"]
    linhas = [
        "# Contrato do sistema Delphi",
        "",
        f"{c['arquivos']} arquivos lidos: {c['unidades']} units, {c['formularios']} formulários, "
        f"{c['componentes']} componentes, {c['eventos']} eventos ({c['eventos_implementados']} implementados), "
        f"{c['sql']} comandos SQL sobre {c['tabelas']} tabelas, {c['pendencias']} pendências.",
        "",
        "## Operações (clique → rotina → SQL)",
        "",
        "| operação | rotina | tabelas | parâmetros | implementada |",
        "|---|---|---|---|---|",
    ]
    for o in contrato["operacoes"]:
        linhas.append(f"| `{o['id']}` | `{o['rotina']}` | {', '.join(o['tabelas']) or '—'} | "
                      f"{', '.join(o['parametros']) or '—'} | {'sim' if o['implementado'] else '**não**'} |")
    linhas += ["", "## Regras com assinatura (interface das units)", ""]
    for u in contrato["unidades"]:
        for r in u["rotinas"]:
            params = ", ".join(f"{p['nome']}: {p['tipo']}" + (f" = {p['padrao']}" if "padrao" in p else "") for p in r["parametros"])
            ret = f": {r['retorno']}" if r.get("retorno") else ""
            linhas.append(f"- `{u['nome']}.{r['nome']}({params}){ret}`")
    if not any(u["rotinas"] for u in contrato["unidades"]):
        linhas.append("Nenhuma lida: o contrato veio do executável, que não guarda a seção interface das units."
                      if contrato["origem"]["tipo"] == "binario" else "Nenhuma.")
    linhas += ["", "## Tabelas", "", "| tabela | onde aparece |", "|---|---|"]
    for t, onde in contrato["tabelas"].items():
        linhas.append(f"| {t} | {', '.join(f'`{o}`' for o in onde)} |")
    linhas += ["", "## Pendências", ""]
    if not contrato["pendencias"]:
        linhas.append("Nenhuma.")
    for p in contrato["pendencias"]:
        linhas.append(f"- **{p['tipo']}** em `{p['onde']}`: {p['detalhe']}")
    return "\n".join(linhas) + "\n"
