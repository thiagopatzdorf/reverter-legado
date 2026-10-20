"""Contrato -> telas web: a mesma tela do Delphi, em HTML, ligada às operações do contrato.

O contrato descarta geometria (o sistema novo desenha do jeito dele), mas para a
primeira versão web a tela original é o melhor ponto de partida: as posições vêm
da mesma árvore TPF0 de onde o contrato saiu (executável ou .dfm), e cada evento
leva o id da operação do contrato. `conferir` prova que nenhum componente nem
evento do contrato ficou de fora da versão web.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import binario, contrato, dfm

# Componentes sem área na tela: o Delphi os mostra como ícone no designer, a web os lista à parte.
NAO_VISUAIS = {
    "TTimer", "TPopupMenu", "TMainMenu", "TMenuItem", "TAction", "TActionList", "TImageList",
    "TImageCollection", "TVirtualImageList", "TOpenDialog", "TSaveDialog", "TFontDialog", "TColorDialog",
    "TApplicationEvents", "TSynCompletionProposal", "TSynURIOpener", "TSynEditSearch", "TSynSQLSyn",
    "TFindDialog", "TReplaceDialog", "TPrintDialog", "TDataSource", "TClientDataSet", "TADOConnection",
    "TADOQuery", "TADOTable", "TQuery", "TTable", "TFDQuery", "TFDConnection", "TOpenTextFileDialog",
    "TTaskDialog", "TTrayIcon", "TBalloonHint", "TJvAppEvents",
}
TEXTO = ("Caption", "Text", "Hint")
LISTAS = ("Items.Strings", "Lines.Strings")


def _nao_visual(classe: str) -> bool:
    return classe in NAO_VISUAIS or classe.startswith("TSyn") and classe.endswith("Syn")


def arvores(caminho: Path) -> list[tuple[str, dict]]:
    """(origem, árvore) de cada tela: dos recursos do executável ou dos .dfm do projeto."""
    caminho = Path(caminho)
    if caminho.is_file() and caminho.suffix.lower() in binario.EXTENSOES:
        dados = caminho.read_bytes()
        return [(f"{caminho.name}:RCDATA/{nome}", dfm.ler_binario(b))
                for nome, b in binario.recursos_rcdata(dados) if b.startswith(b"TPF0")]
    if caminho.is_file():
        base, lista, _ = contrato.do_projeto(caminho)
    else:
        base, lista = caminho, contrato.arquivos(caminho)
    saida = []
    for p in lista:
        if p.suffix.lower() == ".dfm":
            try:
                saida.append((p.relative_to(base).as_posix(), dfm.ler(p.read_bytes())))
            except dfm.DfmInvalido:
                continue  # já é pendência no contrato
    return saida


def _no(n: dict, ops: dict[tuple[str, str], dict], forma: str, w0: int | None = None, h0: int | None = None) -> dict:
    p = n["propriedades"]
    saida = {"n": n["nome"], "c": n["classe"]}
    for chave, prop in (("x", "Left"), ("y", "Top"), ("w", "Width"), ("h", "Height")):
        if isinstance(p.get(prop), int):
            saida[chave] = p[prop]
    if w0 is not None:
        saida.setdefault("w", w0)
        saida.setdefault("h", h0)
    for prop in TEXTO:
        if isinstance(p.get(prop), str) and p[prop]:
            saida["t"] = p[prop]
            break
    for prop in LISTAS:
        if isinstance(p.get(prop), list):
            saida["itens"] = [str(i) for i in p[prop][:12]]
            break
    colunas = p.get("Header.Columns") or p.get("Columns")
    if isinstance(colunas, list):
        saida["col"] = [{"t": str(c.get("Text") or c.get("Caption") or c.get("Title.Caption") or c.get("FieldName") or ""),
                         "w": c.get("Width") if isinstance(c.get("Width"), int) else 80} for c in colunas]
    if p.get("Visible") is False or p.get("TabVisible") is False:
        saida["oculto"] = True
    if isinstance(p.get("Align"), str) and p["Align"] != "alNone":
        saida["a"] = p["Align"]
    if isinstance(p.get("ActivePage"), str):
        saida["ativa"] = p["ActivePage"]
    if p.get("Checked") is True:
        saida["marcado"] = True
    if _nao_visual(n["classe"]):
        saida["nv"] = True
    eventos = []
    for prop, valor in sorted(p.items()):
        if prop.startswith("On") and isinstance(valor, dfm.Ident):
            op = ops.get((n["nome"], prop))
            eventos.append({"e": prop, "h": str(valor), "op": op["id"] if op else None,
                            "ok": bool(op and op["implementado"])})
    if eventos:
        saida["ev"] = eventos
    filhos = []
    for f in n["filhos"]:
        if n["classe"] == "TPageControl" and "w" in saida:
            # TTabSheet não grava geometria: ocupa a área cliente da página (abas no topo).
            filhos.append(_no(f, ops, forma, max(saida["w"] - 8, 0), max(saida["h"] - 28, 0)))
        else:
            filhos.append(_no(f, ops, forma))
    if filhos:
        saida["f"] = filhos
    return saida


def telas(caminho: Path, c: dict | None = None) -> dict:
    c = c or contrato.extrair(caminho)
    por_form: dict[str, dict] = {}
    for o in c["operacoes"]:
        comp, evento = o["gatilho"].split(".", 1)
        por_form.setdefault(o["formulario"], {})[(comp, evento)] = o
    vivas = {f["classe"]: f.get("classe_no_binario", True) for f in c["formularios"]}
    saida = []
    for origem, arvore in arvores(caminho):
        p = arvore["propriedades"]
        raiz = _no(arvore, por_form.get(arvore["nome"], {}), arvore["nome"])
        raiz["w"] = p.get("ClientWidth") or p.get("Width") or 640
        raiz["h"] = p.get("ClientHeight") or p.get("Height") or 480
        raiz.pop("x", None)
        raiz.pop("y", None)
        raiz["origem"] = origem
        raiz["viva"] = vivas.get(arvore["classe"], True)
        saida.append(raiz)
    saida.sort(key=lambda t: t["c"].lower())
    return {"versao": 1, "origem": c["origem"], "cobertura": c["cobertura"], "telas": saida}


def conferir(t: dict, c: dict) -> list[str]:
    """O que o contrato tem e a versão web não. Vazio = toda tela, componente e evento chegou."""
    web_comp, web_ev = set(), set()

    def andar(no: dict, form: str) -> None:
        web_comp.add((form, no["n"]))
        for e in no.get("ev", []):
            web_ev.add((form, no["n"], e["e"], e["h"]))
        for f in no.get("f", []):
            andar(f, form)

    for tela in t["telas"]:
        andar(tela, tela["n"])
    problemas = []
    for f in c["formularios"]:
        for comp in f["componentes"]:
            if (f["nome"], comp["nome"]) not in web_comp:
                problemas.append(f"componente {f['nome']}.{comp['nome']} ({comp['classe']}) ausente da web")
        for e in f["eventos"]:
            if (f["nome"], e["componente"], e["evento"], e["handler"]) not in web_ev:
                problemas.append(f"evento {f['nome']}.{e['componente']}.{e['evento']} ausente da web")
    return problemas


def serializar(t: dict) -> str:
    return json.dumps(t, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
