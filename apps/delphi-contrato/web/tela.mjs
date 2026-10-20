// Desenha na web uma tela Delphi a partir do JSON de `python -m delphi_contrato web`.
//
// É a "linguagem nova" do primeiro passo: a mesma tela, os mesmos componentes e os mesmos
// eventos, cada um ligado ao id da operação do contrato. Posições e tamanhos são os do
// designer do Delphi (pixels a 96 dpi); a janela inteira encolhe para caber no espaço.
// Sem HTML montado por string nem atributo style: só DOM e CSSOM, para rodar sob CSP estrita.

const BOTAO = new Set(["TButton", "TBitBtn", "TSpeedButton", "TToolButton", "INVButton"]);
const CAMPO = new Set(["TEdit", "TButtonedEdit", "TMaskEdit", "TSpinEdit", "TLabeledEdit", "INVEdit", "TDBEdit"]);
const TEXTO_LONGO = new Set(["TMemo", "TSynMemo", "TRichEdit", "TDBMemo"]);
const ROTULO = new Set(["TLabel", "TStaticText", "INVLabel", "TDBText"]);
const MARCA = new Set(["TCheckBox", "INVCheckBox", "TDBCheckBox"]);
const ESCOLHA = new Set(["TComboBox", "TComboBoxEx", "TColorBox", "TDBComboBox", "TDBLookupComboBox"]);
const LISTA = new Set(["TVirtualStringTree", "TListBox", "TListView", "TCheckListBox", "TTreeView", "TStringGrid",
  "TDBGrid", "TValueListEditor"]);
const CAIXA = new Set(["TPanel", "TScrollBox", "TFlowPanel", "TGridPanel", "TToolBar", "TStatusBar", "TFrame"]);
const GRUPO = new Set(["TGroupBox", "TRadioGroup"]);

const semAtalho = (t) => (t || "").replace(/&(.)/g, "$1");
const texto = (no) => semAtalho(no.t ?? "");
const visivel = (no) => no.t ?? no.n; // Caption igual ao Name não é gravado no .dfm: o Delphi mostra o Name.

function el(tag, classe, conteudo) {
  const e = document.createElement(tag);
  if (classe) e.className = classe;
  if (conteudo != null) e.textContent = conteudo;
  return e;
}

function posicionar(e, no) {
  e.style.left = `${no.x ?? 0}px`;
  e.style.top = `${no.y ?? 0}px`;
  if (no.w != null) e.style.width = `${no.w}px`;
  if (no.h != null) e.style.height = `${no.h}px`;
}

function marcar(e, no, ctx) {
  e.dataset.componente = no.n;
  e.dataset.classe = no.c;
  if (no.oculto) e.hidden = true;
  if (no.ev) {
    e.classList.add("dlp-evento");
    if (no.ev.some((x) => !x.ok)) e.classList.add("dlp-sem-codigo");
    e.dataset.eventos = no.ev.map((x) => x.e).join(" ");
    e.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      ctx.aoEvento?.({ componente: no.n, classe: no.c, eventos: no.ev, elemento: e });
    });
  }
}

function controle(no, ctx) {
  const c = no.c;
  let e;
  if (BOTAO.has(c)) {
    e = el("button", "dlp-botao", semAtalho(visivel(no)));
    e.type = "button";
  } else if (CAMPO.has(c)) {
    e = el("input", "dlp-campo");
    e.value = texto(no);
    e.readOnly = true;
    e.setAttribute("aria-label", no.n);
  } else if (TEXTO_LONGO.has(c)) {
    e = el("textarea", "dlp-campo dlp-memo");
    e.value = (no.itens || []).join("\n");
    e.readOnly = true;
    e.setAttribute("aria-label", no.n);
  } else if (ROTULO.has(c)) {
    e = el("span", "dlp-rotulo", semAtalho(visivel(no)));
  } else if (c === "TLinkLabel") {
    e = el("span", "dlp-rotulo dlp-link", semAtalho(visivel(no)).replace(/<[^>]+>/g, ""));
  } else if (MARCA.has(c) || c === "TRadioButton") {
    e = el("label", "dlp-marca");
    const caixa = el("input");
    caixa.type = c === "TRadioButton" ? "radio" : "checkbox";
    caixa.checked = !!no.marcado;
    caixa.tabIndex = -1;
    e.append(caixa, el("span", null, semAtalho(visivel(no))));
  } else if (ESCOLHA.has(c)) {
    e = el("select", "dlp-campo");
    for (const i of no.itens?.length ? no.itens : [texto(no)]) e.append(el("option", null, i));
    e.setAttribute("aria-label", no.n);
  } else if (LISTA.has(c)) {
    e = el("div", "dlp-lista");
    if (no.col?.length) {
      const cab = el("div", "dlp-cab");
      for (const col of no.col) {
        const s = el("span", null, col.t);
        s.style.flexBasis = `${col.w}px`;
        cab.append(s);
      }
      e.append(cab);
    }
    for (const i of no.itens || []) e.append(el("div", "dlp-item", i));
  } else if (c === "TPageControl") {
    e = paginas(no, ctx);
  } else if (GRUPO.has(c)) {
    e = el("fieldset", "dlp-grupo");
    if (no.t) e.append(el("legend", null, texto(no)));
  } else if (CAIXA.has(c) || c === "TTabSheet") {
    e = el("div", c === "TStatusBar" ? "dlp-caixa dlp-status" : "dlp-caixa");
  } else if (c === "TSplitter") {
    e = el("div", "dlp-divisor");
  } else if (c === "TUpDown") {
    e = el("div", "dlp-updown", "▴▾");
  } else if (c === "TProgressBar") {
    e = el("div", "dlp-progresso");
  } else if (c === "TImage") {
    e = el("div", "dlp-imagem");
  } else if (c === "TDateTimePicker") {
    e = el("input", "dlp-campo");
    e.type = "date";
    e.readOnly = true;
  } else {
    // Classe sem desenho próprio: aparece como o que é, nunca some.
    e = el("div", "dlp-outro", c);
  }
  e.classList.add("dlp-c");
  posicionar(e, no);
  marcar(e, no, ctx);
  if (c !== "TPageControl") filhos(e, no, ctx);
  return e;
}

function filhos(pai, no, ctx) {
  for (const f of no.f || []) {
    if (f.nv) ctx.naoVisuais.push(f);
    else pai.append(controle(f, ctx));
  }
}

function paginas(no, ctx) {
  const e = el("div", "dlp-paginas");
  const abas = el("div", "dlp-abas");
  abas.setAttribute("role", "tablist");
  e.append(abas);
  const folhas = (no.f || []).filter((f) => f.c === "TTabSheet");
  const ativa = no.ativa ?? folhas[0]?.n;
  const pares = [];
  for (const folha of folhas) {
    const aba = el("button", "dlp-aba", semAtalho(visivel(folha)));
    aba.type = "button";
    aba.setAttribute("role", "tab");
    const corpo = controle({ ...folha, x: 4, y: 24 }, ctx);
    corpo.setAttribute("role", "tabpanel");
    const mostrar = (sim) => {
      aba.setAttribute("aria-selected", String(sim));
      corpo.classList.toggle("dlp-fora", !sim);
    };
    mostrar(folha.n === ativa);
    aba.addEventListener("click", () => {
      for (const [a, c] of pares) {
        a.setAttribute("aria-selected", "false");
        c.classList.add("dlp-fora");
      }
      mostrar(true);
    });
    pares.push([aba, corpo]);
    if (folha.oculto) aba.hidden = true;
    abas.append(aba);
    e.append(corpo);
  }
  for (const f of no.f || []) {
    if (f.c === "TTabSheet") continue;
    if (f.nv) ctx.naoVisuais.push(f);
    else e.append(controle(f, ctx));
  }
  return e;
}

function naoVisual(no, ctx) {
  const e = el("button", "dlp-nv", `${no.n}: ${no.c}`);
  e.type = "button";
  marcar(e, no, ctx);
  return e;
}

// Desenha `tela` dentro de `alvo`. `aoEvento({componente, classe, eventos, elemento})` é chamado no clique
// de qualquer componente que tem evento no Delphi; `eventos` traz handler, id da operação e se há código.
export function desenhar(tela, alvo, { aoEvento } = {}) {
  const ctx = { aoEvento, naoVisuais: [] };
  alvo.replaceChildren();
  const palco = el("div", "dlp-palco");
  const janela = el("div", "dlp-janela");
  janela.dataset.componente = tela.n;
  janela.dataset.classe = tela.c;
  const barra = el("div", "dlp-titulo", visivel(tela));
  marcar(barra, { ...tela, f: undefined }, ctx);
  barra.dataset.componente = tela.n;
  const area = el("div", "dlp-area");
  area.style.width = `${tela.w}px`;
  area.style.height = `${tela.h}px`;
  filhos(area, tela, ctx);
  janela.append(barra, area);
  palco.append(janela);
  // Menus e ações são centenas numa tela principal: ficam num bloco recolhido, com a contagem.
  const caixa = el("details", "dlp-nao-visuais");
  const bandeja = el("div", "dlp-bandeja");
  // Item de menu é filho de menu: entra na bandeja junto, achatado, para o clique chegar nele.
  const fila = [...ctx.naoVisuais];
  while (fila.length) {
    const nv = fila.shift();
    bandeja.append(naoVisual(nv, ctx));
    fila.unshift(...(nv.f || []));
  }
  caixa.append(el("summary", null, `${bandeja.childElementCount} componentes sem área na tela (menus, ações, timers)`), bandeja);
  if (bandeja.childElementCount) alvo.append(palco, caixa);
  else alvo.append(palco);
  const ajustar = () => {
    const escala = Math.min(1, palco.clientWidth / (tela.w + 2));
    janela.style.transform = `scale(${escala})`;
    palco.style.height = `${(tela.h + 30) * escala}px`;
  };
  ajustar();
  if (typeof ResizeObserver === "function") new ResizeObserver(ajustar).observe(palco);
  return { componentes: alvo.querySelectorAll("[data-componente]").length };
}
