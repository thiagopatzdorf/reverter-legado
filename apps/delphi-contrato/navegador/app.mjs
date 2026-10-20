// A tela da página: entrada, resumo, telas desenhadas por tela.mjs, downloads e comparação.
// Toda a regra está no Python (motor.mjs -> trabalhador.mjs -> delphi_contrato); aqui só se mostra.
import { criarMotor } from "./motor.mjs";
import { desenhar } from "./tela/tela.mjs";
import { registrarFerramentas } from "./agentes.mjs";

const $ = (id) => document.getElementById(id);
const motor = criarMotor();
const estado = { ultimo: null, contrato: null, obter: null, nome: "" };

function el(tag, texto, classe) {
  const e = document.createElement(tag);
  if (texto != null) e.textContent = texto;
  if (classe) e.className = classe;
  return e;
}

function publicar(obj) {
  // O espelho em JSON para quem lê a página por programa (agente, teste): sempre o último estado.
  $("resultado-json").textContent = JSON.stringify(obj, null, 2);
  document.body.dataset.estado = obj.estado;
}

function baixar(nome, texto, tipo) {
  const url = URL.createObjectURL(new Blob([texto], { type: tipo }));
  const a = el("a");
  a.href = url;
  a.download = nome;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const ROTULOS = [
  ["formularios", "telas"], ["componentes", "componentes"], ["eventos", "eventos"],
  ["eventos_implementados", "com código"], ["sql", "SQL"], ["tabelas", "tabelas"], ["pendencias", "pendências"],
];

function mostrarResumo(r, c) {
  const cob = c.cobertura;
  const dl = $("resumo");
  dl.replaceChildren();
  for (const [chave, rotulo] of ROTULOS) {
    const caixa = el("div", null, "numero");
    caixa.append(el("dt", rotulo), el("dd", String(cob[chave] ?? 0)));
    dl.append(caixa);
  }
  const origem = c.origem.tipo === "binario"
    ? `Lido do executável ${c.origem.arquivos[0].caminho} (${c.origem.formato}). Sem o fonte, o clique não chega ao SQL: veja a pendência sem_fonte.`
    : `Lido do fonte: ${cob.arquivos} arquivos, ${cob.unidades} units.`;
  $("resumo-origem").textContent = `${origem} Extraído em ${r.extracao_ms} ms. sha256 ${r.contrato_sha256.slice(0, 16)}…`;
}

function mostrarRecorte(r) {
  const caixa = $("recorte");
  const sel = $("projeto");
  if (!r.projetos.length) {
    caixa.hidden = true;
    return;
  }
  sel.replaceChildren(el("option", "a pasta inteira"));
  sel.firstChild.value = "";
  for (const p of r.projetos) {
    const o = el("option", `só as units de ${p}`);
    o.value = p;
    sel.append(o);
  }
  sel.value = r.projeto || "";
  caixa.hidden = false;
}

function mostrarPendencias(c) {
  const ul = $("pendencias");
  ul.replaceChildren();
  if (!c.pendencias.length) ul.append(el("li", "Nenhuma."));
  for (const p of c.pendencias) {
    const li = el("li");
    li.append(el("b", p.tipo), el("span", ` em ${p.onde}: ${p.detalhe}`));
    ul.append(li);
  }
}

function detalhe(info) {
  const caixa = $("detalhe");
  caixa.replaceChildren();
  document.querySelectorAll(".dlp-ativo").forEach((x) => x.classList.remove("dlp-ativo"));
  info.elemento.classList.add("dlp-ativo");
  caixa.append(el("h4", `${info.componente} (${info.classe})`));
  for (const ev of info.eventos) {
    const op = estado.contrato.operacoes.find((o) => o.id === ev.op);
    const bloco = el("div", null, "operacao");
    bloco.append(el("p", `${ev.e} → ${ev.h}`, "evento-nome"));
    const dl = el("dl");
    const linha = (k, v) => dl.append(el("dt", k), el("dd", v));
    linha("operação", ev.op || "—");
    linha("tem código", ev.ok ? "sim" : "não (pendência)");
    if (op) {
      linha("rotina", op.rotina);
      linha("chama", op.chama.join(", ") || "—");
      linha("tabelas", op.tabelas.join(", ") || "—");
      linha("parâmetros", op.parametros.join(", ") || "—");
      linha("SQL", op.sql.join("; ") || (estado.contrato.origem.tipo === "binario" ? "só com o fonte ou o REA" : "—"));
    }
    bloco.append(dl);
    caixa.append(bloco);
  }
}

function mostrarTela() {
  const telas = estado.ultimo.telas.telas;
  const t = telas.find((x) => x.n === $("tela").value) || telas[0];
  if (!t) {
    $("palco").replaceChildren(el("p", "Nenhuma tela neste arquivo."));
    return;
  }
  desenhar(t, $("palco"), { aoEvento: detalhe });
}

function mostrarTelas(r) {
  const sel = $("tela");
  sel.replaceChildren();
  for (const t of r.telas.telas) {
    const o = el("option", `${t.n} (${t.c})${t.viva === false ? ", sem código no .exe" : ""}`);
    o.value = t.n;
    sel.append(o);
  }
  // Abre na primeira tela com algo para ver: um data module só tem componentes sem área.
  const visual = r.telas.telas.find((t) => (t.f || []).some((f) => !f.nv));
  if (visual) sel.value = visual.n;
  mostrarTela();
}

async function extrair(obter, nome, projeto) {
  estado.obter = obter;
  estado.nome = nome;
  publicar({ estado: "extraindo", acao: "extrair", arquivo: nome });
  $("motor-estado").textContent = `Lendo ${nome}…`;
  try {
    const r = await motor.extrair(await obter(), { projeto });
    const c = JSON.parse(r.contrato);
    estado.ultimo = r;
    estado.contrato = c;
    mostrarResumo(r, c);
    mostrarRecorte(r);
    mostrarTelas(r);
    mostrarPendencias(c);
    $("contrato-json").textContent = r.contrato;
    const aviso = $("aviso-web");
    aviso.hidden = !r.faltando_na_web.length;
    aviso.textContent = `${r.faltando_na_web.length} item(ns) do contrato não couberam no desenho das telas.`;
    $("resultado").hidden = false;
    $("motor-estado").textContent = `Pronto: ${nome}.`;
    publicar({
      estado: "feito", acao: "extrair", arquivo: nome, projeto: r.projeto, tipo: r.tipo,
      contrato_sha256: r.contrato_sha256, extracao_ms: r.extracao_ms, cobertura: c.cobertura,
      projetos: r.projetos, telas: r.telas.telas.map((t) => t.n), pendencias: c.pendencias,
      operacoes: c.operacoes.map((o) => ({ id: o.id, implementado: o.implementado, tabelas: o.tabelas })),
    });
    return r;
  } catch (erro) {
    $("motor-estado").textContent = `Não deu para ler ${nome}: ${erro.message}`;
    publicar({ estado: "erro", acao: "extrair", arquivo: nome, erro: erro.message });
    throw erro;
  }
}

const deArquivos = (lista) => {
  const arquivos = [...lista];
  return [() => Promise.resolve(arquivos), arquivos.map((a) => a.name).join(", ")];
};

async function exemplo(nome) {
  const r = await fetch(`exemplos/${nome}`);
  return { nome, dados: await r.arrayBuffer() };
}
const deExemplo = (nome) => [async () => [await exemplo(nome)], nome];

async function comparar(obterExe, obterFonte, rotulo) {
  publicar({ estado: "comparando", acao: "comparar", arquivos: rotulo });
  $("comparar-veredito").textContent = "Comparando…";
  try {
    const r = await motor.comparar(await obterExe(), await obterFonte());
    $("comparar-veredito").textContent = r.confere
      ? `Confere: ${r.telas_identicas} de ${r.telas_em_comum} telas idênticas.`
      : `Diverge: ${r.telas_identicas} de ${r.telas_em_comum} telas idênticas.`;
    const pre = $("comparacao-json");
    pre.textContent = JSON.stringify(r, null, 2);
    pre.hidden = false;
    publicar({ estado: "feito", acao: "comparar", arquivos: rotulo, comparacao: r });
    return r;
  } catch (erro) {
    $("comparar-veredito").textContent = `Não deu para comparar: ${erro.message}`;
    publicar({ estado: "erro", acao: "comparar", erro: erro.message });
    throw erro;
  }
}

const ignorar = () => {};

function ligar() {
  $("arquivo").addEventListener("change", (e) => {
    if (e.target.files.length) extrair(...deArquivos(e.target.files)).catch(ignorar);
  });
  const zona = $("soltar");
  zona.addEventListener("dragover", (e) => {
    e.preventDefault();
    zona.classList.add("sobre");
  });
  zona.addEventListener("dragleave", () => zona.classList.remove("sobre"));
  zona.addEventListener("drop", (e) => {
    e.preventDefault();
    zona.classList.remove("sobre");
    if (e.dataTransfer.files.length) extrair(...deArquivos(e.dataTransfer.files)).catch(ignorar);
  });
  $("exemplo-zip").addEventListener("click", () => extrair(...deExemplo("cadastro.zip")).catch(ignorar));
  $("exemplo-exe").addEventListener("click", () => extrair(...deExemplo("Cadastro.exe")).catch(ignorar));
  $("projeto").addEventListener("change", (e) => extrair(estado.obter, estado.nome, e.target.value || null).catch(ignorar));
  $("tela").addEventListener("change", mostrarTela);
  $("baixar-json").addEventListener("click", () => baixar("contrato.json", estado.ultimo.contrato, "application/json"));
  $("baixar-md").addEventListener("click", () => baixar("contrato.md", estado.ultimo.relatorio, "text/markdown"));
  $("comparar-botao").addEventListener("click", () => {
    const exe = $("comparar-exe").files;
    const fonte = $("comparar-fonte").files;
    if (!exe.length || !fonte.length) {
      $("comparar-veredito").textContent = "Escolha o executável e o fonte.";
      return;
    }
    const [x] = deArquivos(exe);
    const [f] = deArquivos(fonte);
    comparar(x, f, `${exe[0].name} × ${[...fonte].map((a) => a.name).join(", ")}`).catch(ignorar);
  });
  $("comparar-exemplo").addEventListener("click", () => {
    comparar(async () => [await exemplo("Cadastro.exe")], async () => [await exemplo("cadastro.zip")],
      "Cadastro.exe × cadastro.zip").catch(ignorar);
  });
}

ligar();
const api = {
  pronto: motor.pronto,
  extrair: (arquivos, opcoes = {}) => extrair(() => Promise.resolve(arquivos), arquivos.map((a) => a.nome ?? a.name).join(", "), opcoes.projeto),
  comparar: (executavel, fonte) => comparar(() => Promise.resolve(executavel), () => Promise.resolve(fonte), "api"),
  exemplo,
  arquivoEscolhido: () => [...$("arquivo").files],
};
window.delphiContrato = api;
$("webmcp-estado").textContent = registrarFerramentas(api);

motor.pronto.then((m) => {
  $("motor-estado").textContent = `Motor pronto (Python no navegador, Pyodide ${m.versao}, carregado em ${m.carga_ms} ms). Escolha um arquivo.`;
  if (document.body.dataset.estado === "carregando") publicar({ estado: "pronto", motor: m });
}, (erro) => {
  $("motor-estado").textContent = `O motor não carregou: ${erro.message}`;
  publicar({ estado: "erro", erro: erro.message });
});
