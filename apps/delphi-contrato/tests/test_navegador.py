"""Guardas da página do navegador: o contrato de lá é o da CLI, byte a byte, e o arquivo não sai.

Os testes rápidos rodam a ponte no CPython (a mesma que roda no Pyodide). O de ponta a
ponta monta a página com o Pyodide fixado e a abre num Chromium headless; ele é pulado,
dizendo o motivo, onde não há Node, Playwright, Chromium ou o Pyodide (rede).
"""
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent
NAV = APP / "navegador"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(NAV))
sys.path.insert(0, str(APP / "tests"))

import montar  # noqa: E402
import ponte  # noqa: E402
from delphi_contrato import contrato  # noqa: E402
from sintetico import CADASTRO, cadastro_exe  # noqa: E402

DOURADO = APP / "tests" / "fixtures" / "cadastro.contrato.json"


def _arquivo(tmp_path, nome, dados):
    p = tmp_path / "recebido" / nome
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(dados)
    return p


def _zip(itens: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, dados in itens.items():
            z.writestr(nome, dados)
    return buf.getvalue()


def test_zip_do_projeto_no_navegador_da_contrato_diferente_da_cli(tmp_path):
    z = _arquivo(tmp_path, "cadastro.zip", montar.exemplos()["exemplos/cadastro.zip"])
    r = ponte.extrair([z], tmp_path / "area")
    assert r["contrato"] == DOURADO.read_text(encoding="utf-8")
    assert r["contrato_sha256"] == hashlib.sha256(DOURADO.read_bytes()).hexdigest()
    assert r["projetos"] == ["Cadastro.dpr"] and not r["faltando_na_web"]


def test_executavel_no_navegador_da_contrato_diferente_da_cli(tmp_path):
    exe = _arquivo(tmp_path, "Cadastro.exe", cadastro_exe())
    cli = contrato.serializar(contrato.extrair(exe))
    assert ponte.extrair([exe], tmp_path / "area")["contrato"] == cli


def test_dpr_escolhido_no_zip_diverge_da_cli_com_o_dpr(tmp_path):
    z = _arquivo(tmp_path, "cadastro.zip", montar.exemplos()["exemplos/cadastro.zip"])
    r = ponte.extrair([z], tmp_path / "area", projeto="Cadastro.dpr")
    assert r["contrato"] == contrato.serializar(contrato.extrair(CADASTRO / "Cadastro.dpr"))
    with pytest.raises(ponte.EntradaInvalida):
        ponte.extrair([z], tmp_path / "area", projeto="../fora.dpr")


def test_dfm_solto_nao_vira_a_mesma_pasta_da_cli(tmp_path):
    dfm = _arquivo(tmp_path, "UClientes.dfm", (CADASTRO / "UClientes.dfm").read_bytes())
    pasta = tmp_path / "so-dfm"
    pasta.mkdir()
    shutil.copy(CADASTRO / "UClientes.dfm", pasta)
    assert ponte.extrair([dfm], tmp_path / "area")["contrato"] == contrato.serializar(contrato.extrair(pasta))


def test_zip_com_caminho_para_fora_da_pasta_e_aceito(tmp_path):
    z = _arquivo(tmp_path, "mau.zip", _zip({"../../fora.pas": b"unit Fora; interface implementation end."}))
    with pytest.raises(ponte.EntradaInvalida, match="fora do zip"):
        ponte.extrair([z], tmp_path / "area")
    assert not (tmp_path / "fora.pas").exists()


def test_zip_portable_com_varios_binarios_nao_acha_o_do_sistema(tmp_path):
    # Como o zip oficial do HeidiSQL: o sistema, um utilitário .exe e DLLs de terceiros sem tela Delphi.
    sem_tela = b"MZ" + b"\0" * 200
    z = _arquivo(tmp_path, "Portable.zip", _zip({"plink.exe": sem_tela, "libmysql.dll": sem_tela,
                                                  "Cadastro.exe": cadastro_exe(), "LEIA.txt": b"oi"}))
    r = ponte.extrair([z], tmp_path / "area")
    exe = _arquivo(tmp_path, "Cadastro.exe", cadastro_exe())
    assert r["tipo"] == "executavel" and r["contrato"] == contrato.serializar(contrato.extrair(exe))


def test_comparar_os_exemplos_no_navegador_diverge(tmp_path):
    exe = _arquivo(tmp_path, "Cadastro.exe", cadastro_exe())
    z = _arquivo(tmp_path, "cadastro.zip", montar.exemplos()["exemplos/cadastro.zip"])
    r = ponte.comparar([exe], [z], tmp_path / "area")
    assert r["confere"] and r["telas_em_comum"] == 2
    erro = json.loads(ponte.chamar("comparar", json.dumps({"area": str(tmp_path / "a2"), "executavel": [str(z)],
                                                           "fonte": [str(z)]})))
    assert erro == {"ok": False, "erro": erro["erro"]} and "executável" in erro["erro"]


def test_montar_sem_pyodide_muda_de_bytes_entre_duas_rodadas(tmp_path):
    a = montar.montar(tmp_path / "a", com_pyodide=False)
    b = montar.montar(tmp_path / "b", com_pyodide=False)
    assert a == b
    for nome, info in a["arquivos"].items():
        assert hashlib.sha256((tmp_path / "a" / nome).read_bytes()).hexdigest() == info["sha256"], nome
    # O pacote servido é o do fonte, não uma cópia mantida à mão.
    assert (tmp_path / "a" / "py" / "delphi_contrato" / "contrato.py").read_bytes() == \
        (APP / "delphi_contrato" / "contrato.py").read_bytes()


def test_csp_da_pagina_diverge_da_do_cabecalho():
    meta = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', (NAV / "index.html").read_text())
    assert meta and meta.group(1) == montar.CSP
    assert f"Content-Security-Policy: {montar.CSP}" in montar.headers("/experimente/").decode()
    assert "connect-src 'self'" in montar.CSP and "'unsafe-eval'" not in montar.CSP.replace("'wasm-unsafe-eval'", "")


def test_pyodide_do_trabalhador_nao_e_o_fixado():
    pasta = f"pyodide-{montar.PIN['versao']}"
    texto = (NAV / "trabalhador.mjs").read_text()
    assert set(re.findall(r"pyodide-[\d.]+", texto)) == {pasta}


def test_pagina_tem_script_estilo_ou_endereco_externo():
    html = (NAV / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "script inline quebra a CSP"
    assert "<style" not in html and not re.search(r'\sstyle="', html) and not re.search(r"\son[a-z]+=", html)
    for p in NAV.glob("*.mjs"):
        if p.name != "conferir.mjs":
            assert not re.search(r"https?://", p.read_text()), f"{p.name}: endereço absoluto (a página só busca a si mesma)"


def _node(codigo: str) -> str:
    if not shutil.which("node"):
        pytest.skip("sem node")
    return subprocess.run(["node", "--input-type=module", "-e", codigo], capture_output=True, text=True,
                          check=True, timeout=60).stdout


def test_webmcp_ausente_quebra_a_pagina_ou_registro_falha():
    uri = (NAV / "agentes.mjs").as_uri()
    saida = _node(f"""
const m = await import({json.dumps(uri)});
const api = {{ exemplo: async () => ({{ nome: "x", dados: new ArrayBuffer(0) }}), arquivoEscolhido: () => [],
  extrair: async () => ({{ contrato: '{{"cobertura":{{}},"pendencias":[],"operacoes":[]}}', contrato_sha256: "s", projetos: [] }}),
  comparar: async () => ({{ confere: true }}) }};
const sem = m.registrarFerramentas(api, {{ document: {{}}, navigator: {{}} }});
const reg = [];
const com = m.registrarFerramentas(api, {{ document: {{ modelContext: {{ registerTool: (t) => reg.push(t) }} }} }});
const velho = m.registrarFerramentas(api, {{ navigator: {{ modelContext: {{ registerTool: (t) => reg.push(t) }} }} }});
const r = JSON.parse(await reg[0].execute('{{"exemplo":"cadastro_zip"}}'));
console.log(JSON.stringify({{ sem, com, velho, nomes: reg.map((t) => t.name), sha: r.contrato_sha256 }}));
""")
    r = json.loads(saida)
    assert "não oferece WebMCP" in r["sem"]
    assert r["com"] == r["velho"] == "Ferramentas WebMCP registradas: extrair_contrato, comparar."
    assert r["nomes"] == ["extrair_contrato", "comparar"] * 2 and r["sha"] == "s"


# ------------------------------------------------------------------ ponta a ponta no Chromium

def _playwright() -> Path | None:
    if not shutil.which("node") or not shutil.which("npm"):
        return None
    raiz = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    p = Path(raiz) / "playwright"
    return p if p.is_dir() else None


@pytest.fixture(scope="module")
def no_chromium(tmp_path_factory):
    pw = _playwright()
    if not pw:
        pytest.skip("sem Node + Playwright global")
    try:
        montar.pyodide()
    except OSError as erro:
        pytest.skip(f"Pyodide fora do cache e sem rede: {erro}")
    import servir

    dist = tmp_path_factory.mktemp("dist")
    montar.montar(dist)
    saida = tmp_path_factory.mktemp("conferir")
    s = servir.servidor(dist)
    try:
        r = subprocess.run(["node", str(NAV / "conferir.mjs"), f"http://127.0.0.1:{s.server_address[1]}/index.html",
                            str(saida)], capture_output=True, text=True, timeout=600,
                           env={**__import__("os").environ, "PLAYWRIGHT_MODULE": str(pw)})
    finally:
        s.shutdown()
    if r.returncode and "Executable doesn't exist" in r.stderr:
        pytest.skip("Playwright sem Chromium instalado")
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads((saida / "resultado.json").read_text()), saida


def test_contrato_baixado_no_chromium_diverge_da_cli(no_chromium, tmp_path):
    r, _ = no_chromium
    exe = _arquivo(tmp_path, "Cadastro.exe", cadastro_exe())
    esperado = {"exemplo-zip": hashlib.sha256(DOURADO.read_bytes()).hexdigest(),
                "exemplo-exe": hashlib.sha256(contrato.serializar(contrato.extrair(exe)).encode()).hexdigest()}
    assert {c["entrada"]: c["baixado_sha256"] for c in r["casos"]} == esperado
    assert r["comparacao"]["confere"] is True
    assert "CLIENTES" in r["clique"] and "FrmClientes.BtnSalvar.OnClick" in r["clique"]


def test_arquivo_do_usuario_sai_do_navegador(no_chromium):
    r, _ = no_chromium
    assert r["pedidos_externos"] == [] and r["pedidos_com_corpo"] == []
    assert all(p["metodo"] == "GET" for p in r["pedidos"])
    assert r["violacoes_csp"] == [] and r["erros_console"] == []


def test_pagina_estoura_390px_ou_webmcp_simulado_falha(no_chromium):
    r, saida = no_chromium
    assert r["largura_390"]["documento"] <= r["largura_390"]["janela"] == 390
    assert (saida / "390.png").stat().st_size > 0
    assert r["webmcp_simulado"]["nomes"] == ["comparar", "extrair_contrato"]
    assert r["webmcp_simulado"]["extrair_sha256"] == hashlib.sha256(DOURADO.read_bytes()).hexdigest()
    assert r["webmcp_simulado"]["comparar_confere"] is True
