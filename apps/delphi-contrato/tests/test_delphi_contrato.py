"""Guardas do Delphi -> contrato: o contrato é determinístico, não esconde buraco,
e o avaliador pega contrato que deixou de ser o do fonte."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from delphi_contrato import contrato, dfm, pascal, rea  # noqa: E402
from delphi_contrato.__main__ import main  # noqa: E402
from sintetico import tpf0 as _encode  # noqa: E402

FIXTURE = APP / "tests" / "fixtures" / "cadastro"
DOURADO = APP / "tests" / "fixtures" / "cadastro.contrato.json"
FITA = APP.parent.parent / "factory.manifest.json"


@pytest.fixture
def projeto(tmp_path):
    destino = tmp_path / "cadastro"
    shutil.copytree(FIXTURE, destino)
    return destino


def _operacao(c, ident):
    return next(o for o in c["operacoes"] if o["id"] == ident)


def test_contrato_do_exemplo_mudou_sem_atualizar_o_dourado():
    gerado = contrato.serializar(contrato.extrair(FIXTURE))
    assert gerado == DOURADO.read_text(encoding="utf-8"), (
        "o extrator mudou a saída: confira o diff e regenere com "
        "`python -m delphi_contrato extrair tests/fixtures/cadastro -o tests/fixtures/cadastro.contrato.json`"
    )


def test_mesmo_fonte_em_outra_pasta_gera_bytes_diferentes(projeto):
    assert contrato.serializar(contrato.extrair(projeto)) == contrato.serializar(contrato.extrair(FIXTURE))
    assert str(projeto.parent) not in contrato.serializar(contrato.extrair(projeto))


def test_clique_perde_o_sql_da_rotina_chamada_e_do_dataset_aberto():
    c = contrato.extrair(FIXTURE)
    salvar = _operacao(c, "FrmClientes.BtnSalvar.OnClick")
    assert salvar["chama"] == ["TDmDados.ProximoCodigo", "TFrmClientes.CpfValido"]
    assert salvar["tabelas"] == ["CLIENTES"]
    assert salvar["parametros"] == ["CODIGO", "CPF", "NOME"]
    mostrar = _operacao(c, "FrmClientes.FrmClientes.OnShow")
    assert mostrar["sql"] == ["UDados.dfm:QryClientes.SQL.Strings"]
    assert mostrar["tabelas"] == ["CIDADES", "CLIENTES"]


def test_botao_ligado_a_handler_sem_corpo_some_em_silencio():
    c = contrato.extrair(FIXTURE)
    assert _operacao(c, "FrmClientes.BtnExcluir.OnClick")["implementado"] is False
    tipos = {(p["tipo"], p["detalhe"].split(" ")[0]) for p in c["pendencias"]}
    assert ("evento_sem_implementacao", "TFrmClientes.BtnExcluirClick") in tipos
    assert ("metodo_sem_corpo", "TFrmClientes.BtnExcluirClick") in tipos


def test_parambyname_vaza_para_dentro_do_texto_do_sql():
    u = pascal.ler_unidade((FIXTURE / "UClientes.pas").read_text(encoding="utf-8"), "UClientes.pas")
    (insert,) = u["sql"]
    assert insert["texto"] == "INSERT INTO CLIENTES (CODIGO, NOME, CPF) VALUES (:CODIGO, :NOME, :CPF)"
    assert "dinamico" not in insert


def test_sql_montado_com_variavel_passa_como_estatico():
    u = pascal.ler_unidade((FIXTURE / "UDados.pas").read_text(encoding="utf-8"), "UDados.pas")
    (select,) = u["sql"]
    assert select["dinamico"] is True and select["tabelas"] == []
    assert u["campos_lidos"] == ["ULTIMO"]


def test_comentario_e_aspas_dobradas_quebram_o_lexer():
    fonte = """unit U; interface
    { comentário com 'aspas' e procedure Falsa; }
    (* outro: function Fantasma: Integer; *)
    procedure Real(const S: string = 'it''s'); // procedure Comentada;
    implementation
    procedure Real(const S: string);
    begin
      Q.SQL.Text := 'SELECT * FROM T WHERE N = ''x''' + #13#10 + 'AND Y = 1';
      Q.Open;
    end;
    end."""
    u = pascal.ler_unidade(fonte, "U.pas")
    assert [r["nome"] for r in u["rotinas"]] == ["Real"]
    assert u["rotinas"][0]["parametros"][0]["padrao"] == "'it''s'"
    assert u["sql"][0]["texto"] == "SELECT * FROM T WHERE N = 'x' AND Y = 1"
    assert u["implementadas"] == ["Real"]


def test_dpr_deixa_entrar_demo_de_biblioteca_de_terceiros(projeto):
    demo = projeto / "terceiros" / "Demo"
    demo.mkdir(parents=True)
    (demo / "uMain.pas").write_text("unit uMain; interface type TMain = class(TForm) end; implementation end.", encoding="utf-8")
    (demo / "uMain.dfm").write_text("object Main: TMain\nend\n", encoding="utf-8")
    pela_pasta = contrato.extrair(projeto)
    pelo_projeto = contrato.extrair(projeto / "Cadastro.dpr")
    assert "TMain" in {f["classe"] for f in pela_pasta["formularios"]}
    assert {f["classe"] for f in pelo_projeto["formularios"]} == {"TFrmClientes", "TDmDados"}
    assert pelo_projeto["operacoes"] == contrato.extrair(FIXTURE)["operacoes"]


def test_unit_declarada_no_dpr_sem_arquivo_some_em_silencio(projeto):
    dpr = projeto / "Cadastro.dpr"
    dpr.write_text(dpr.read_text(encoding="utf-8").replace("UClientes in 'UClientes.pas' {FrmClientes};",
                   "UClientes in 'UClientes.pas' {FrmClientes},\n  UPerdida in 'velho\\UPerdida.pas';"), encoding="utf-8")
    c = contrato.extrair(dpr)
    assert {"tipo": "unit_ausente", "onde": "velho\\UPerdida.pas",
            "detalhe": "declarada no projeto, arquivo não encontrado"} in c["pendencias"]


def test_tipo_procedural_com_cdecl_encerra_a_secao_type():
    fonte = """unit U; interface
    type
      TCallback = procedure(userData: Pointer; zName: PAnsiChar); cdecl;
      TLib = class(TObject)
        sqlite3_open: function(const filename: PAnsiChar): Integer; cdecl;
      public
        procedure Carregar;
      end;
      TOutra=
        class(TList)
        public
          constructor Create;
        end;
    implementation
    procedure TLib.Carregar; begin end;
    constructor TOutra.Create; begin end;
    end."""
    u = pascal.ler_unidade(fonte, "U.pas")
    assert u["rotinas"] == []
    assert [c["nome"] for c in u["classes"]] == ["TLib", "TOutra"]
    assert [f["nome"] for f in u["classes"][0]["campos"]] == ["sqlite3_open"]


def test_variavel_de_tipo_procedure_engole_as_rotinas_seguintes():
    fonte = """unit U; interface
    function IsWine: Boolean;
    function DirSep: Char;
    var Gancho: procedure(A: Integer); stdcall;
    implementation
    function IsWine: Boolean;
    var
      wine_nt_to_unix_file_name: procedure(p1: pointer; p2: pointer); stdcall;
    begin
      Result := Assigned(wine_nt_to_unix_file_name);
    end;
    function DirSep: Char;
    type
      TOriginal = procedure of object;
    begin
      if IsWine then Result := '/' else Result := '\\';
    end;
    end."""
    u = pascal.ler_unidade(fonte, "U.pas")
    assert [r["nome"] for r in u["rotinas"]] == ["IsWine", "DirSep"]
    assert u["implementadas"] == ["IsWine", "DirSep"]


def test_metodo_de_interface_vira_rotina_solta_sem_corpo(tmp_path):
    (tmp_path / "UContratos.pas").write_text("""unit UContratos; interface
    type
      IRepositorio = interface(IInterface)
        ['{6A1B2C3D-0000-0000-0000-000000000001}']
        function Buscar(Id: Integer): string;
        procedure Gravar(const Valor: string);
      end;
      TPonto = object
        X, Y: Integer;
        procedure Mover(DX: Integer);
      end;
    implementation
    procedure TPonto.Mover(DX: Integer);
    begin
      X := X + DX;
    end;
    end.""", encoding="utf-8")
    c = contrato.extrair(tmp_path)
    (u,) = c["unidades"]
    assert u["rotinas"] == []
    assert [m["nome"] for m in u["interfaces"][0]["metodos"]] == ["Buscar", "Gravar"]
    assert [k["nome"] for k in c["classes"]] == ["TPonto"]
    assert c["pendencias"] == []


@pytest.mark.parametrize("arquivo", ["UClientes.dfm", "UDados.dfm"])
def test_dfm_binario_e_texto_dao_arvores_diferentes(arquivo):
    texto = dfm.ler((FIXTURE / arquivo).read_bytes())
    assert dfm.ler(_encode(texto)) == texto


def test_projeto_com_dfm_binario_muda_o_contrato(projeto):
    caminho = projeto / "UClientes.dfm"
    caminho.write_bytes(_encode(dfm.ler(caminho.read_bytes())))
    a, b = contrato.extrair(projeto), contrato.extrair(FIXTURE)
    a.pop("origem"), b.pop("origem")  # o sha256 muda; o contrato não
    assert a == b


def test_dfm_em_cp1252_com_acento_nao_e_lido(projeto):
    caminho = projeto / "UClientes.dfm"
    caminho.write_bytes(caminho.read_text(encoding="utf-8").replace("Cadastro de Clientes", "Edição").encode("cp1252"))
    form = next(f for f in contrato.extrair(projeto)["formularios"] if f["nome"] == "FrmClientes")
    assert form["propriedades"]["Caption"] == "Edição"


def test_dfm_quebrado_derruba_a_extracao_inteira(projeto):
    (projeto / "UQuebrado.dfm").write_text("object X: TForm\n  Caption = 'sem end'\n", encoding="utf-8")
    c = contrato.extrair(projeto)
    assert any(p["tipo"] == "arquivo_ilegivel" and p["onde"] == "UQuebrado.dfm" for p in c["pendencias"])
    assert c["cobertura"]["formularios"] == 2


def test_verificar_aceita_contrato_editado_a_mao(projeto):
    c = json.loads(DOURADO.read_text(encoding="utf-8"))
    assert contrato.verificar(c, projeto) == []
    c["operacoes"][0]["implementado"] = True
    assert any("operacoes" in p for p in contrato.verificar(c, projeto))


def test_verificar_aceita_fonte_que_mudou_depois(projeto):
    c = json.loads(DOURADO.read_text(encoding="utf-8"))
    pas = projeto / "UDados.pas"
    pas.write_text(pas.read_text(encoding="utf-8").replace("Percentual > 15", "Percentual > 20"), encoding="utf-8")
    assert any("origem" in p for p in contrato.verificar(c, projeto))


def test_estrito_deixa_passar_pendencia_aberta(projeto):
    c = json.loads(DOURADO.read_text(encoding="utf-8"))
    assert contrato.verificar(c, projeto) == []
    assert contrato.verificar(c, projeto, estrito=True) == ["3 pendência(s) em aberto (--estrito)"]


def test_cli_verificar_sai_zero_com_contrato_divergente(projeto, tmp_path, capsys):
    editado = tmp_path / "c.json"
    c = json.loads(DOURADO.read_text(encoding="utf-8"))
    c["tabelas"]["FANTASMA"] = []
    editado.write_text(json.dumps(c), encoding="utf-8")
    assert main(["verificar", str(DOURADO), str(projeto)]) == 0
    assert main(["verificar", str(editado), str(projeto)]) == 1


def test_relatorio_omite_operacao_sem_implementacao():
    md = contrato.relatorio(json.loads(DOURADO.read_text(encoding="utf-8")))
    assert "| `FrmClientes.BtnExcluir.OnClick` | `TFrmClientes.BtnExcluirClick` | — | — | **não** |" in md
    assert "`UDados.CalcularDesconto(Valor: Currency, Percentual: Double = 0): Currency`" in md


# ------------------------------------------------------------------ REA


def test_rea_seco_executa_alguma_coisa(tmp_path):
    exe = tmp_path / "Cadastro.exe"
    exe.write_bytes(b"MZ" + b"\x00" * 62)
    chamadas = []
    plano = rea.executar(exe, tmp_path / "ev", rodar=lambda argv: chamadas.append(argv))
    assert plano["aplicado"] is False and chamadas == []
    assert not (tmp_path / "ev").exists()
    assert all(p["argv"][:3] == ["npx", "-y", f"rea-agents@{rea.VERSAO_REA}"] for p in plano["passos"])


def test_rea_exit_zero_sem_json_conta_como_evidencia(tmp_path):
    exe = tmp_path / "Cadastro.exe"
    exe.write_bytes(b"MZ")
    plano = rea.executar(exe, tmp_path / "ev", aplicar=True,
                         rodar=lambda argv: subprocess.CompletedProcess(argv, 0, b"ghidra nao instalado", b""))
    assert plano["ok"] is False
    assert all(p["codigo"] == -1 for p in plano["passos"])


def test_rea_evidencia_sem_sha256_nao_prova_nada(tmp_path):
    exe = tmp_path / "Cadastro.exe"
    exe.write_bytes(b"MZ")
    saida = json.dumps({"functions": 12}).encode()
    plano = rea.executar(exe, tmp_path / "ev", aplicar=True,
                         rodar=lambda argv: subprocess.CompletedProcess(argv, 0, saida, b""))
    assert plano["ok"] is True
    registro = json.loads((tmp_path / "ev" / "rea-evidencia.json").read_text(encoding="utf-8"))
    assert {p["sha256"] for p in registro["passos"]} == {__import__("hashlib").sha256(saida).hexdigest()}


def test_versao_do_rea_na_fita_diverge_da_do_codigo():
    fita = json.loads(FITA.read_text(encoding="utf-8"))
    papel = fita["papeis"]["reverso"]
    (ferramenta,) = [f for f in papel["ferramentas"] if f["nome"] == "rea"]
    assert ferramenta["pacote"] == f"{rea.PACOTE}@{rea.VERSAO_REA}"
    assert any(f"{rea.PACOTE}@{rea.VERSAO_REA}" in prova for prova in papel["prova"])
    assert fita["ligacoes"]["reverso"] in fita["substratos"]


# ------------------------------------------------------------------ protótipo


def test_pagina_do_prototipo_ficou_velha_em_relacao_ao_contrato():
    import importlib.util

    spec = importlib.util.spec_from_file_location("montar", APP / "prototipo" / "montar.py")
    montar = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(montar)
    pagina = montar.montar()
    assert pagina == (APP / "prototipo" / "index.html").read_text(encoding="utf-8"), (
        "regenere com `python3 apps/delphi-contrato/prototipo/montar.py`"
    )
    assert "/*__DADOS__*/" not in pagina and "</script>" not in pagina.split("const DADOS = ", 1)[1].split(";\n", 1)[0]


# ------------------------------------------------------------------ executável


def _exe(tmp_path, metodos=None):
    from sintetico import METODOS_CADASTRO, cadastro_exe

    caminho = tmp_path / "Cadastro.exe"
    caminho.write_bytes(cadastro_exe(metodos or METODOS_CADASTRO))
    return caminho


def test_executavel_perde_telas_que_o_fonte_tem(tmp_path):
    do_exe = contrato.extrair(_exe(tmp_path))
    do_fonte = contrato.extrair(FIXTURE)
    assert do_exe["origem"]["tipo"] == "binario" and do_exe["origem"]["formato"] == "PE32"
    sem_arquivo = lambda fs: [{k: v for k, v in f.items() if k not in ("arquivo", "unidade", "eventos", "classe_no_binario")} for f in fs]  # noqa: E731
    assert sem_arquivo(do_exe["formularios"]) == sem_arquivo(sorted(do_fonte["formularios"], key=lambda f: f["classe"]))
    assert do_exe["cobertura"]["rcdata_nao_formulario"] == 1


def test_handler_fora_da_tabela_de_metodos_passa_como_implementado(tmp_path):
    c = contrato.extrair(_exe(tmp_path))
    estado = {o["gatilho"]: o["implementado"] for o in c["operacoes"]}
    assert estado == {"BtnExcluir.OnClick": False, "BtnSalvar.OnClick": True, "FrmClientes.OnShow": True}
    assert any(p["tipo"] == "sem_fonte" for p in c["pendencias"])


def test_tela_cuja_classe_o_linker_removeu_vira_ruido_de_handlers(tmp_path):
    c = contrato.extrair(_exe(tmp_path, metodos=("TDmDados",)))
    tipos = [p["tipo"] for p in c["pendencias"]]
    assert tipos.count("tela_sem_codigo") == 1 and "evento_sem_implementacao" not in tipos
    assert not any(o["implementado"] for o in c["operacoes"])


def test_sql_em_utf16_e_ansi_do_codigo_some_do_contrato(tmp_path):
    c = contrato.extrair(_exe(tmp_path))
    textos = {(s["operacao"], s.get("codificacao")): s["tabelas"] for s in c["sql"]}
    assert textos[("INSERT", "utf-16")] == ["CLIENTES"]
    assert textos[("SELECT", "ansi")] == []
    assert textos[("SELECT", None)] == ["CIDADES", "CLIENTES"]  # SQL.Strings do TPF0, não duplicado pela varredura
    assert len(c["sql"]) == 3


def test_executavel_gera_bytes_diferentes_e_verificar_nao_confere(tmp_path):
    exe = _exe(tmp_path)
    a = contrato.serializar(contrato.extrair(exe))
    assert a == contrato.serializar(contrato.extrair(exe))
    assert contrato.verificar(json.loads(a), exe) == []
    exe.write_bytes(exe.read_bytes() + b"\x00")
    assert any("origem" in p for p in contrato.verificar(json.loads(a), exe))


def test_arquivo_que_nao_e_executavel_quebra_sem_explicar(tmp_path):
    from delphi_contrato import binario

    falso = tmp_path / "x.exe"
    falso.write_bytes(b"isto nao e um PE")
    with pytest.raises(binario.BinarioInvalido, match="MZ"):
        contrato.extrair(falso)


def test_cli_extrair_nao_aceita_executavel(tmp_path, capsys):
    saida = tmp_path / "c.json"
    assert main(["extrair", str(_exe(tmp_path)), "-o", str(saida)]) == 0
    assert json.loads(saida.read_text(encoding="utf-8"))["cobertura"]["formularios"] == 2



# ------------------------------------------------------------------ web


def test_versao_web_perde_componente_ou_evento_do_contrato(tmp_path):
    from delphi_contrato import web

    for origem in (FIXTURE, _exe(tmp_path)):
        c = contrato.extrair(origem)
        t = web.telas(origem, c)
        assert web.conferir(t, c) == []
        clientes = next(x for x in t["telas"] if x["n"] == "FrmClientes")
        clientes["f"] = [f for f in clientes["f"] if f["n"] != "EdtCpf"]
        for f in clientes["f"]:
            f.pop("ev", None)
        problemas = web.conferir(t, c)
        assert "componente FrmClientes.EdtCpf (TEdit) ausente da web" in problemas
        assert "evento FrmClientes.BtnSalvar.OnClick ausente da web" in problemas


def test_evento_web_sem_id_da_operacao_do_contrato():
    from delphi_contrato import web

    t = web.telas(FIXTURE)
    clientes = next(x for x in t["telas"] if x["n"] == "FrmClientes")
    botoes = {f["n"]: f for f in clientes["f"]}
    assert botoes["BtnSalvar"]["ev"] == [{"e": "OnClick", "h": "BtnSalvarClick", "op": "FrmClientes.BtnSalvar.OnClick", "ok": True}]
    assert botoes["BtnExcluir"]["ev"][0]["ok"] is False
    assert botoes["DsClientes"]["nv"] is True and (clientes["w"], clientes["h"]) == (480, 320)


def test_aba_do_pagecontrol_fica_sem_tamanho():
    from delphi_contrato import dfm, web

    arvore = dfm.ler_texto("""object F: TF
  object P: TPageControl
    Left = 0
    Top = 0
    Width = 300
    Height = 200
    ActivePage = A
    object A: TTabSheet
      Caption = 'Aba'
    end
  end
end
""")
    no = web._no(arvore, {}, "F")
    aba = no["f"][0]["f"][0]
    assert (aba["w"], aba["h"], aba["t"]) == (292, 172, "Aba")


def test_cli_web_grava_versao_incompleta(tmp_path, monkeypatch):
    from delphi_contrato import web

    saida = tmp_path / "telas.json"
    assert main(["web", str(FIXTURE), "-o", str(saida)]) == 0
    assert len(json.loads(saida.read_text(encoding="utf-8"))["telas"]) == 2
    monkeypatch.setattr(web, "conferir", lambda t, c: ["componente X.Y ausente da web"])
    saida.unlink()
    assert main(["web", str(FIXTURE), "-o", str(saida)]) == 1
    assert not saida.exists()



def test_comparar_esconde_tela_que_mudou_entre_exe_e_fonte(tmp_path, projeto):
    from delphi_contrato import comparar

    exe = _exe(tmp_path, metodos=("TFrmClientes", "FormShow", "BtnSalvarClick"))
    r = comparar.comparar(contrato.extrair(exe), contrato.extrair(FIXTURE))
    assert (r["telas_em_comum"], r["telas_identicas"]) == (2, 2)
    assert r["telas_sem_codigo_no_exe"] == ["TDmDados"]
    dfm_ = projeto / "UClientes.dfm"
    dfm_.write_text(dfm_.read_text(encoding="utf-8").replace("MaxLength = 11", "MaxLength = 14"), encoding="utf-8")
    r = comparar.comparar(contrato.extrair(exe), contrato.extrair(projeto))
    assert r["telas_identicas"] == 1
    assert r["diferentes"] == [{"tela": "TFrmClientes", "componentes": 2, "eventos": 0, "propriedades_da_tela": False}]
    assert main(["comparar", str(exe), str(projeto)]) == 1
