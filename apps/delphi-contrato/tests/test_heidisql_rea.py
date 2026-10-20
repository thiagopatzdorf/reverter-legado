"""O veredito do REA no HeidiSQL sai das marcas e da evidência, nunca de alguém dizendo "bateu"."""
import hashlib
import importlib.util
import json
import shutil
import struct
from pathlib import Path

import pytest

CASOS = Path(__file__).resolve().parent.parent / "casos"


def gerador():
    spec = importlib.util.spec_from_file_location("heidisql_rea", CASOS / "heidisql_rea.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tabela(g):
    return json.loads((g.EVIDENCIA / "tabela-de-metodos.json").read_text(encoding="utf-8"))


def test_veredito_medido_muda_sem_ninguem_mexer_na_evidencia():
    g = gerador()
    m = g.medir(tabela(g))
    vereditos = {h["handler"].split(".", 1)[1]: h["veredito"] for h in m["handlers"]}
    assert vereditos == {
        "btnRestoreDefaultsClick": "igual", "btnDonatedOKClick": "igual", "btnAddColClick": "igual",
        "btnOkClick": "sem_tratamento_de_erro", "menuFormatCodeOnceClick": "sem_tratamento_de_erro",
    }
    assert m["resumo"]["marcas_normais_vistas"] == m["resumo"]["marcas_normais"]
    assert m["resumo"]["marcas_excecao_vistas"] == 0


def test_funcao_do_rea_diferente_da_tabela_de_metodos_passa_despercebida():
    g = gerador()
    assert all(h["confere_com_a_tabela"] for h in g.medir(tabela(g))["handlers"])
    trocada = {k: ["0xdead"] for k in tabela(g)}
    assert not any(h["confere_com_a_tabela"] for h in g.medir(trocada)["handlers"])


def test_pseudo_codigo_sem_um_fato_do_fonte_continua_igual(tmp_path, monkeypatch):
    g = gerador()
    copia = tmp_path / "evidencia"
    shutil.copytree(g.EVIDENCIA, copia)
    alvo = copia / "pseudo" / "TAboutBox.btnDonatedOKClick.c.txt"
    alvo.write_text(alvo.read_text(encoding="utf-8").replace('L"Thanks for donating!"', "local_38"), encoding="utf-8")
    monkeypatch.setattr(g, "EVIDENCIA", copia)
    h = next(x for x in g.medir(tabela(g))["handlers"] if x["handler"] == "TAboutBox.btnDonatedOKClick")
    assert h["veredito"] == "diverge"
    assert h["faltou"] == ["doação confirmada"]


def test_tabela_de_metodos_lida_errado_do_binario(tmp_path, monkeypatch):
    # Entrada x64 do Delphi: tamanho (word) + endereço (8 bytes) + nome em ShortString.
    nome = b"btnOkClick"
    entrada = struct.pack("<HQ", 2 + 8 + 1 + len(nome), 0xE98350) + bytes([len(nome)]) + nome
    # Nome solto, fora de entrada (texto qualquer), não pode virar endereço.
    exe = tmp_path / "x.exe"
    exe.write_bytes(b"\0" * 64 + entrada + b"\0" * 16 + bytes([len(nome)]) + nome + b"\0" * 16)
    g = gerador()
    monkeypatch.setattr(g, "EXE_SHA256", hashlib.sha256(exe.read_bytes()).hexdigest())
    assert g.tabela_de_metodos(exe, ["TfrmReformatter.btnOkClick"]) == {"TfrmReformatter.btnOkClick": ["0xe98350"]}


def test_exe_que_nao_e_o_da_release_e_aceito(tmp_path):
    exe = tmp_path / "x.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(SystemExit):
        gerador().tabela_de_metodos(exe, [])
