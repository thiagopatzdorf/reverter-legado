// Confere a página montada num Chromium de verdade: o contrato baixado (bytes), a rede, a CSP,
// o WebMCP e as capturas de tela em 390 px e em desktop.
//
//   PLAYWRIGHT_MODULE=<caminho do pacote playwright> node conferir.mjs <url> <pasta de saída> [arquivo ...]
//
// Sem arquivos, roda os dois exemplos da página. Escreve <saída>/resultado.json e os .png.
// Variáveis opcionais: CHROMIUM_EXECUTAVEL (binário do Chromium).
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const [url, saida, ...arquivos] = process.argv.slice(2);
mkdirSync(saida, { recursive: true });
const sha = (b) => createHash("sha256").update(b).digest("hex");
const origem = new URL(url).origin;

const navegador = await chromium.launch(process.env.CHROMIUM_EXECUTAVEL ? { executablePath: process.env.CHROMIUM_EXECUTAVEL } : {});
const resultado = { navegador: navegador.version(), casos: [], pedidos: [], violacoes_csp: [], erros_console: [] };

async function pagina(contexto, nome, opcoes = {}) {
  const p = await contexto.newPage(opcoes);
  p.on("request", (r) => resultado.pedidos.push({ pagina: nome, metodo: r.method(), url: r.url(),
    corpo: r.postDataBuffer() ? r.postDataBuffer().length : 0, tipo: r.resourceType() }));
  p.on("console", (m) => {
    if (m.type() === "error") resultado.erros_console.push({ pagina: nome, texto: m.text() });
  });
  // Violações da CSP no documento e no trabalhador chegam como evento: guardamos todas.
  await p.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      (window.__violacoes ||= []).push(`${e.violatedDirective} ${e.blockedURI}`);
    });
  });
  const t0 = Date.now();
  await p.goto(url);
  await p.waitForFunction(() => ["pronto", "erro"].includes(document.body.dataset.estado), null, { timeout: 120000 });
  const pronto = JSON.parse(await p.textContent("#resultado-json"));
  return { p, pronto, carga_total_ms: Date.now() - t0 };
}

async function extrairPela(p, acao) {
  await acao();
  await p.waitForFunction(() => ["feito", "erro"].includes(document.body.dataset.estado), null, { timeout: 300000 });
  const r = JSON.parse(await p.textContent("#resultado-json"));
  if (r.estado !== "feito") return r;
  const [download] = await Promise.all([p.waitForEvent("download"), p.click("#baixar-json")]);
  const caminho = join(saida, `${r.arquivo}.contrato.json`);
  await download.saveAs(caminho);
  const [md] = await Promise.all([p.waitForEvent("download"), p.click("#baixar-md")]);
  await md.saveAs(join(saida, `${r.arquivo}.contrato.md`));
  return { ...r, baixado_sha256: sha(readFileSync(caminho)), baixado_nome: download.suggestedFilename(), operacoes: undefined, pendencias: undefined };
}

// 1. Desktop: exemplos (ou arquivos dados), download, clique numa tela, comparação.
const ctx = await navegador.newContext({ acceptDownloads: true, viewport: { width: 1280, height: 900 } });
const { p, pronto, carga_total_ms } = await pagina(ctx, "desktop");
resultado.motor = { ...pronto.motor, carga_total_ms };
if (arquivos.length) {
  for (const a of arquivos) {
    const r = await extrairPela(p, () => p.setInputFiles("#arquivo", a));
    resultado.casos.push({ entrada: basename(a), ...r });
  }
} else {
  resultado.casos.push({ entrada: "exemplo-zip", ...(await extrairPela(p, () => p.click("#exemplo-zip"))) });
  await p.screenshot({ path: join(saida, "desktop-fonte.png"), fullPage: true });
  // Clique no botão Salvar desenhado: tem de mostrar a operação do contrato com a tabela.
  await p.click('[data-componente="BtnSalvar"]');
  resultado.clique = await p.textContent("#detalhe");
  resultado.casos.push({ entrada: "exemplo-exe", ...(await extrairPela(p, () => p.click("#exemplo-exe"))) });
  await p.click("#comparar-exemplo");
  await p.waitForFunction(() => document.body.dataset.estado !== "comparando", null, { timeout: 120000 });
  resultado.comparacao = JSON.parse(await p.textContent("#resultado-json")).comparacao;
}
resultado.webmcp_texto = await p.textContent("#webmcp-estado");
resultado.violacoes_csp.push(...(await p.evaluate(() => window.__violacoes || [])));
await p.screenshot({ path: join(saida, "desktop.png"), fullPage: true });

// 2. Celular, 390 px: a mesma página sem rolagem horizontal.
if (!arquivos.length) {
  const cel = await navegador.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const m = await pagina(cel, "390px");
  await m.p.click("#exemplo-zip");
  await m.p.waitForFunction(() => document.body.dataset.estado === "feito", null, { timeout: 120000 });
  await m.p.click('[data-componente="BtnSalvar"]');
  resultado.largura_390 = await m.p.evaluate(() => ({ documento: document.documentElement.scrollWidth, janela: innerWidth }));
  await m.p.screenshot({ path: join(saida, "390.png"), fullPage: true });
  resultado.violacoes_csp.push(...(await m.p.evaluate(() => window.__violacoes || [])));

  // 3. WebMCP simulado: o navegador daqui (Chromium 141) não tem a API; a simulação prova o nosso lado.
  const ag = await navegador.newContext();
  const a = await ag.newPage();
  await a.addInitScript(() => {
    window.__ferramentas = [];
    Object.defineProperty(document, "modelContext", { value: { registerTool: (t) => { window.__ferramentas.push(t); } } });
  });
  await a.goto(url);
  await a.waitForFunction(() => document.body.dataset.estado === "pronto", null, { timeout: 120000 });
  resultado.webmcp_simulado = await a.evaluate(async () => {
    const f = Object.fromEntries(window.__ferramentas.map((t) => [t.name, t]));
    const ex = JSON.parse(await f.extrair_contrato.execute({ exemplo: "cadastro_zip" }, {}));
    const cp = JSON.parse(await f.comparar.execute(JSON.stringify({ executavel_exemplo: "cadastro_exe", fonte_exemplo: "cadastro_zip" }), {}));
    return { nomes: Object.keys(f).sort(), extrair_sha256: ex.contrato_sha256, comparar_confere: cp.confere,
      texto: document.getElementById("webmcp-estado").textContent };
  });
}

resultado.pedidos_externos = resultado.pedidos.filter((r) => !r.url.startsWith(origem) && !r.url.startsWith("blob:") && !r.url.startsWith("data:"));
resultado.pedidos_com_corpo = resultado.pedidos.filter((r) => r.metodo !== "GET" || r.corpo > 0);
writeFileSync(join(saida, "resultado.json"), JSON.stringify(resultado, null, 2));
await navegador.close();
console.log(JSON.stringify({ casos: resultado.casos.map((c) => [c.entrada, c.estado, c.baixado_sha256, c.extracao_ms]),
  externos: resultado.pedidos_externos.length, com_corpo: resultado.pedidos_com_corpo.length, csp: resultado.violacoes_csp.length }));
