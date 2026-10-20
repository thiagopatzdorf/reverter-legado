"""Testes do rea-lab: gabarito do fonte, medição, comandos do REA e o leitor de WAD tirado do binário."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
RAIZ = APP.parents[1]
CASO = APP / "casos" / "chocolate-doom"
sys.path.insert(0, str(APP))

from rea_lab import fonte, medir, rea, wad

# --- gabarito do fonte -------------------------------------------------------------------

def test_gabarito_acha_funcao_kr_e_ignora_chave_dentro_de_comentario_e_de_texto():
    r = fonte.ler_arquivo(APP / "tests" / "fixtures" / "mini.c", "mini.c")
    assert [(f["nome"], f["linha"], f["static"]) for f in r["funcoes"]] == [
        ("P_Interna", 10, True), ("W_Conta", 15, False)]


def test_gabarito_nao_conta_tabela_inicializada_nem_ponteiro_de_funcao_como_funcao():
    nomes = {f["nome"] for f in fonte.ler_arquivo(APP / "tests" / "fixtures" / "mini.c", "mini.c")["funcoes"]}
    assert "tabela" not in nomes and "ponteiro" not in nomes


def test_gabarito_tira_escape_do_literal_e_ignora_include():
    lits = [l["texto"] for l in fonte.ler_arquivo(APP / "tests" / "fixtures" / "mini.c", "mini.c")["literais"]]
    assert lits[0] == "Wad file %s doesn't have IWAD or PWAD id\n"
    assert all("stdio" not in l for l in lits)


def test_gabarito_lista_arquivo_que_falta_em_vez_de_contar_zero_em_silencio(tmp_path):
    g = fonte.gabarito(tmp_path, ["nao_existe.c"])
    assert g["faltando"] == ["nao_existe.c"] and g["arquivos"] == 0


# --- medição ----------------------------------------------------------------------------

def _gabarito(funcoes=(), literais=()):
    return {"funcoes": [{"nome": n, "static": False} for n in funcoes], "funcoes_total": len(funcoes),
            "funcoes_static": 0, "literais": [{"texto": t} for t in literais]}


def test_literal_concatenado_no_c_conta_como_achado_quando_o_binario_tem_o_texto_inteiro():
    textos = [{"endereco": "0x1", "texto": "Wad file %s doesn't have IWAD or PWAD id\n"}]
    m = medir.medir([], textos, _gabarito(literais=["Wad file %s doesn't have IWAD ", "or PWAD id\n", "nada disso"]))
    assert m["fonte_literais_unicos_min6"] == 3 and m["fonte_literais_achados_no_binario"] == 2


def test_nome_generico_do_ghidra_nao_conta_como_nome_recuperado():
    procs = [{"endereco": "0x1", "nome": "FUN_140001000", "externo": False, "thunk": False},
             {"endereco": "0x2", "nome": "thunk_FUN_140001000", "externo": False, "thunk": True},
             {"endereco": "0x3", "nome": "W_AddFile", "externo": False, "thunk": False},
             {"endereco": "EXTERNAL:0x1", "nome": "SDL2.DLL::SDL_Init", "externo": True, "thunk": False}]
    m = medir.medir(procs, [], _gabarito(funcoes=["W_AddFile", "G_Ticker"]))
    assert (m["rea_procedimentos_proprios"], m["rea_procedimentos_com_nome"], m["rea_nomes_que_batem_com_o_fonte"]) == (2, 1, 1)
    assert m["rea_procedimentos_externos"] == 1 and m["rea_procedimentos_thunk"] == 1


def test_numeros_publicados_do_rea_saem_da_evidencia_e_nao_foram_digitados():
    ev = CASO / "evidencia"
    procs = json.loads(gzip.decompress((ev / "procedimentos.json.gz").read_bytes()))
    textos = json.loads(gzip.decompress((ev / "textos.json.gz").read_bytes()))
    publicado = json.loads((ev / "metricas.json").read_text(encoding="utf-8"))
    refeito = medir.medir(procs, textos, _gabarito())
    for chave, valor in refeito.items():
        if chave.startswith("rea_"):
            assert publicado[chave] == valor, chave


def test_readme_cita_os_numeros_da_evidencia():
    m = json.loads((CASO / "evidencia" / "metricas.json").read_text(encoding="utf-8"))
    readme = (APP / "README.md").read_text(encoding="utf-8")
    for chave in ("rea_procedimentos_total", "rea_procedimentos_proprios", "rea_textos_total", "fonte_funcoes_teto",
                  "fonte_literais_unicos_min6", "fonte_literais_achados_no_binario"):
        assert f"{m[chave]:,}".replace(",", ".") in readme, chave


def test_evidencia_no_repo_bate_com_o_sha256_registrado_no_caso():
    caso = json.loads((CASO / "caso.json").read_text(encoding="utf-8"))
    for rel, esperado in caso["evidencia_sha256"].items():
        assert hashlib.sha256((CASO / "evidencia" / rel).read_bytes()).hexdigest() == esperado, rel


def test_nome_de_evidencia_ao_lado_de_sha256_dispara_o_gitleaks():
    # "resumo" contém "sumo": o gitleaks lê nome + sha256 como token da Sumo Logic e reprova o PR.
    caso = json.loads((CASO / "caso.json").read_text(encoding="utf-8"))
    assert [rel for rel in caso["evidencia_sha256"] if "sumo" in rel.lower()] == []


# --- comandos do REA --------------------------------------------------------------------

def test_versao_do_rea_igual_a_da_fita_e_a_do_delphi_contrato():
    fita = (RAIZ / "factory.manifest.json").read_text(encoding="utf-8")
    delphi = (RAIZ / "apps" / "delphi-contrato" / "delphi_contrato" / "rea.py").read_text(encoding="utf-8")
    assert f"rea-agents@{rea.VERSAO_REA}" in fita
    assert re.search(rf'VERSAO_REA = "{re.escape(rea.VERSAO_REA)}"', delphi)


def test_conteiner_do_rea_nasce_sem_rede_com_alvo_so_leitura_e_teto_de_cpu_e_memoria():
    argv = rea.conteiner("rj-sessao", "ALVO", "SAIDA")
    juntos = " ".join(argv)
    assert "--network none" in juntos and "ALVO:/alvo:ro" in juntos
    assert "--cpus 2" in juntos and "--memory 8g" in juntos


def test_conteiner_sem_prefixo_rj_e_recusado_porque_a_limpeza_nao_o_acharia():
    with pytest.raises(ValueError):
        rea.conteiner("rea-x", "a", "b")


def test_passo_do_rea_recusa_comando_que_executa_o_alvo_ou_argumento_com_shell():
    with pytest.raises(ValueError):
        rea.passo("rj-sessao", "capture-process", [])
    with pytest.raises(ValueError):
        rea.passo("rj-sessao", "search", ["/alvo/x.exe", "IWAD; rm -rf /"])
    assert rea.passo("rj-sessao", "search", ["/alvo/x.exe", "IWAD"])[-2:] == ["json", "--full-output"]


# --- WAD e save, formatos tirados do binário ----------------------------------------------

def _wad(ident=b"IWAD", lumps=(("E1M1", b""), ("THINGS", b"\x01\x02"))):
    corpo, dirs, pos = b"", b"", 12
    for nome, dados in lumps:
        dirs += struct.pack("<ii8s", pos, len(dados), nome.encode())
        corpo += dados
        pos += len(dados)
    return ident + struct.pack("<ii", len(lumps), 12 + len(corpo)) + corpo + dirs


def test_wad_sintetico_e_lido_com_diretorio_no_offset_do_cabecalho(tmp_path):
    p = tmp_path / "t.wad"
    p.write_bytes(_wad())
    r = wad.resumo(p)
    assert (r["identificacao"], r["numlumps"], r["mapas"], r["lumps_vazios"]) == ("IWAD", 2, ["E1M1"], 1)
    assert r["diretorio_termina_no_fim_do_arquivo"] and r["lumps_fora_do_arquivo"] == []


def test_wad_com_identificacao_que_o_jogo_recusa_tambem_e_recusado():
    with pytest.raises(wad.WadInvalido):
        wad.ler(_wad(ident=b"ZWAD"))


def test_wad_com_diretorio_alem_do_fim_do_arquivo_e_recusado():
    dados = bytearray(_wad())
    struct.pack_into("<i", dados, 4, 99)
    with pytest.raises(wad.WadInvalido):
        wad.ler(bytes(dados))


def test_pwad_acima_do_limite_vanilla_que_o_binario_impoe_e_sinalizado(tmp_path):
    p = tmp_path / "grande.wad"
    p.write_bytes(_wad(ident=b"PWAD", lumps=[(f"L{i}", b"") for i in range(wad.LIMITE_LUMPS_PWAD + 1)]))
    assert wad.resumo(p)["acima_do_limite_vanilla_de_pwad"] is True
    assert wad.LIMITE_LUMPS_PWAD == 4046


# Gabarito copiado de src/w_wad.c (3.1.1, linhas 38-52): wadinfo_t e filelump_t empacotados.
WADINFO_T = [("identificacao", 0, 4), ("numlumps", 4, 4), ("infotableofs", 8, 4)]
FILELUMP_T = [("filepos", 0, 4), ("size", 4, 4), ("name", 8, 8)]


def test_layout_do_wad_tirado_do_binario_bate_com_os_structs_do_fonte():
    assert [(c, o, t) for c, o, t, *_ in wad.CABECALHO] == WADINFO_T
    assert [(c, o, t) for c, o, t, *_ in wad.ENTRADA] == FILELUMP_T
    assert (wad.TAMANHO_CABECALHO, wad.TAMANHO_ENTRADA) == (12, 16)


def test_versao_do_save_tirada_do_binario_bate_com_G_VanillaVersionCode():
    # src/d_mode.h: exe_doom_1_2=0, 1_5=1, 1_666=2, 1_7=3, 1_8=4, 1_9=5, hacx=6...
    assert [wad.versao_do_save(v) for v in range(8)] == [109, 109, 106, 107, 108, 109, 109, 109]


def test_cabecalho_do_save_nao_tem_buraco_nem_sobreposicao():
    fim = 0
    for _campo, offset, tamanho, *_ in wad.SAVE_CABECALHO:
        assert offset == fim
        fim += tamanho
    assert fim == wad.TAMANHO_SAVE_CABECALHO == 24 + 16 + 3 + 4 + 3
