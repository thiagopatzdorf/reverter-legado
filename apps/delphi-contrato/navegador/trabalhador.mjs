// Trabalhador (Web Worker): o Python do extrator roda aqui, fora da linha da tela.
//
// Sobe o Pyodide servido do próprio domínio e o MESMO pacote delphi_contrato da CLI, copiado
// pelo montar.py. Os arquivos do usuário chegam como bytes por postMessage, vão para o
// sistema de arquivos em memória do Pyodide e somem na próxima chamada. Nenhum fetch leva
// conteúdo do usuário: os únicos pedidos de rede daqui são GET dos arquivos estáticos abaixo.
import { loadPyodide } from "./pyodide-314.0.7/pyodide.mjs";

const BASE = new URL("./", import.meta.url);
const INDICE = new URL("./pyodide-314.0.7/", BASE).href;

async function bytes(caminho) {
  const r = await fetch(new URL(caminho, BASE));
  if (!r.ok) throw new Error(`${caminho}: HTTP ${r.status}`);
  return new Uint8Array(await r.arrayBuffer());
}

const motor = (async () => {
  const t0 = performance.now();
  // packageBaseUrl no próprio domínio: o padrão do Pyodide é o CDN jsDelivr, que a CSP recusaria.
  const py = await loadPyodide({ indexURL: INDICE, packageBaseUrl: INDICE, stdout: () => {}, stderr: () => {} });
  const lista = JSON.parse(new TextDecoder().decode(await bytes("py/arquivos.json")));
  py.FS.mkdirTree("/app/delphi_contrato");
  for (const nome of lista) py.FS.writeFile(`/app/${nome}`, await bytes(`py/${nome}`));
  py.runPython("import sys\nsys.path.insert(0, '/app')\nimport ponte");
  return { py, chamar: py.globals.get("ponte").chamar, ms: Math.round(performance.now() - t0) };
})();

let rodada = 0;

function gravar(py, pasta, arquivos) {
  py.FS.mkdirTree(pasta);
  return arquivos.map((a, i) => {
    // Um subdiretório por arquivo: dois arquivos com o mesmo nome não se sobrescrevem.
    const dir = `${pasta}/${i}`;
    py.FS.mkdirTree(dir);
    const nome = a.nome.split(/[\\/]/).pop() || "arquivo";
    py.FS.writeFile(`${dir}/${nome}`, new Uint8Array(a.dados));
    return `${dir}/${nome}`;
  });
}

function apagar(py, caminho) {
  const st = py.FS.analyzePath(caminho);
  if (!st.exists) return;
  if (py.FS.isDir(st.object.mode)) {
    for (const n of py.FS.readdir(caminho)) if (n !== "." && n !== "..") apagar(py, `${caminho}/${n}`);
    py.FS.rmdir(caminho);
  } else py.FS.unlink(caminho);
}

self.onmessage = async ({ data }) => {
  const { id, acao } = data;
  try {
    const { py, chamar, ms } = await motor;
    if (acao === "iniciar") {
      self.postMessage({ id, ok: true, resultado: { versao: py.version, carga_ms: ms } });
      return;
    }
    const raiz = `/recebido/${++rodada}`;
    const pedido = { area: `/area/${rodada}`, projeto: data.projeto || null };
    if (acao === "extrair") pedido.entradas = gravar(py, `${raiz}/e`, data.arquivos);
    else if (acao === "comparar") {
      pedido.executavel = gravar(py, `${raiz}/x`, data.executavel);
      pedido.fonte = gravar(py, `${raiz}/f`, data.fonte);
    }
    const resposta = JSON.parse(chamar(acao, JSON.stringify(pedido)));
    apagar(py, raiz);
    apagar(py, pedido.area);
    self.postMessage({ id, ...resposta });
  } catch (erro) {
    self.postMessage({ id, ok: false, erro: String(erro && erro.message ? erro.message : erro) });
  }
};
