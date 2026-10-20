// API do extrator no navegador, sobre o trabalhador. Quem embute a página (ou um agente) usa
// esta interface; a tela (app.mjs) e as ferramentas WebMCP (agentes.mjs) também.
//
//   const m = criarMotor();             // começa a carregar o Python em segundo plano
//   await m.pronto;                     // {versao, carga_ms}
//   await m.extrair([file], {projeto})  // {contrato, contrato_sha256, relatorio, telas, ...}
//   await m.comparar([exe], [zip])      // o mesmo JSON de `python3 -m delphi_contrato comparar`
//
// Os arquivos são lidos aqui (File.arrayBuffer) e vão só para o trabalhador, na mesma aba.

async function paraBytes(arquivos) {
  return Promise.all(arquivos.map(async (a) => ({
    nome: a.nome ?? a.name,
    dados: a.dados ?? (await a.arrayBuffer()),
  })));
}

export function criarMotor(url = new URL("./trabalhador.mjs", import.meta.url)) {
  const trabalhador = new Worker(url, { type: "module" });
  const pendentes = new Map();
  let proximo = 0;
  trabalhador.onmessage = ({ data }) => {
    const p = pendentes.get(data.id);
    if (!p) return;
    pendentes.delete(data.id);
    if (data.ok) p.resolve(data.resultado);
    else p.reject(new Error(data.erro));
  };
  trabalhador.onerror = (e) => {
    for (const p of pendentes.values()) p.reject(new Error(e.message || "falha ao carregar o motor"));
    pendentes.clear();
  };
  const pedir = (msg, transferir = []) => new Promise((resolve, reject) => {
    const id = ++proximo;
    pendentes.set(id, { resolve, reject });
    trabalhador.postMessage({ id, ...msg }, transferir);
  });
  const pronto = pedir({ acao: "iniciar" });
  return {
    pronto,
    async extrair(arquivos, { projeto } = {}) {
      const lista = await paraBytes(arquivos);
      return pedir({ acao: "extrair", arquivos: lista, projeto }, lista.map((a) => a.dados));
    },
    async comparar(executavel, fonte, { projeto } = {}) {
      const x = await paraBytes(executavel);
      const f = await paraBytes(fonte);
      return pedir({ acao: "comparar", executavel: x, fonte: f, projeto }, [...x, ...f].map((a) => a.dados));
    },
  };
}
