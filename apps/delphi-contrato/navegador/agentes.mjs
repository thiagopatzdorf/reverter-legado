// Ferramentas para agentes de IA pelo WebMCP (proposta do W3C Web Machine Learning CG).
//
// O WebMCP ainda não é padrão: o rascunho de 2026-07 moveu a API de navigator.modelContext para
// document.modelContext, e o Chrome a oferece só em origin trial (149 a 156) ou com a flag
// chrome://flags/#enable-webmcp-testing. Por isso: detecção de recurso, nada quebra onde não
// existe, e a mesma operação continua disponível pela tela e por window.delphiContrato.
// O retorno de execute é texto (JSON), como o rascunho pede.

const LIMITE_CONTRATO = 200_000; // caracteres: acima disso o agente baixa o arquivo pela tela

function base64ParaBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

async function entrada(api, args, prefixo = "") {
  const exemplo = args[`${prefixo}exemplo`];
  const conteudo = args[`${prefixo}conteudo_base64`];
  if (exemplo) return [await api.exemplo(exemplo === "cadastro_exe" ? "Cadastro.exe" : "cadastro.zip")];
  if (conteudo) return [{ nome: args[`${prefixo}nome`] || "entrada.zip", dados: base64ParaBytes(conteudo) }];
  return null;
}

const ler = (args) => (typeof args === "string" ? JSON.parse(args || "{}") : args || {});

export function ferramentas(api) {
  const ARQUIVO = {
    exemplo: { type: "string", enum: ["cadastro_zip", "cadastro_exe"], description: "usa um exemplo embutido na página" },
    nome: { type: "string", description: "nome do arquivo, com a extensão (.exe, .dll, .bpl, .zip, .dfm)" },
    conteudo_base64: { type: "string", description: "o arquivo em base64; fica neste navegador, não é enviado" },
  };
  return [
    {
      name: "extrair_contrato",
      description: "Lê um sistema Delphi (.exe/.dll/.bpl sem fonte, ou .zip do projeto com .dpr/.pas/.dfm) e devolve o "
        + "contrato JSON: telas, componentes, eventos, SQL, operações (clique -> SQL) e pendências. Sem argumento, usa o "
        + "arquivo escolhido em #arquivo. Roda localmente no navegador.",
      inputSchema: {
        type: "object",
        properties: { ...ARQUIVO, projeto: { type: "string", description: "um .dpr de dentro do zip: lê só as units dele" } },
      },
      annotations: { readOnlyHint: true },
      async execute(args) {
        const a = ler(args);
        const arquivos = (await entrada(api, a)) || api.arquivoEscolhido();
        if (!arquivos.length) return JSON.stringify({ erro: "nenhum arquivo: passe exemplo ou conteudo_base64" });
        const r = await api.extrair(arquivos, { projeto: a.projeto });
        const c = JSON.parse(r.contrato);
        return JSON.stringify({
          contrato_sha256: r.contrato_sha256, cobertura: c.cobertura, pendencias: c.pendencias, operacoes: c.operacoes,
          projetos: r.projetos,
          contrato: r.contrato.length <= LIMITE_CONTRATO ? c : "grande demais para a resposta: use o botão Baixar contrato.json",
        });
      },
    },
    {
      name: "comparar",
      description: "Compara o contrato de um executável Delphi com o do fonte: as telas batem componente por componente "
        + "e evento por evento? Devolve o mesmo JSON de `python3 -m delphi_contrato comparar`.",
      inputSchema: {
        type: "object",
        properties: {
          executavel_exemplo: { type: "string", enum: ["cadastro_exe"] },
          executavel_nome: ARQUIVO.nome, executavel_conteudo_base64: ARQUIVO.conteudo_base64,
          fonte_exemplo: { type: "string", enum: ["cadastro_zip"] },
          fonte_nome: ARQUIVO.nome, fonte_conteudo_base64: ARQUIVO.conteudo_base64,
        },
      },
      annotations: { readOnlyHint: true },
      async execute(args) {
        const a = ler(args);
        const exe = await entrada(api, a, "executavel_");
        const fonte = await entrada(api, a, "fonte_");
        if (!exe || !fonte) return JSON.stringify({ erro: "passe o executável e o fonte (exemplo ou conteudo_base64)" });
        return JSON.stringify(await api.comparar(exe, fonte));
      },
    },
  ];
}

// Registra as ferramentas se o navegador tiver WebMCP. Devolve a frase para a página dizer o que aconteceu.
export function registrarFerramentas(api, alvo = globalThis) {
  const mc = alvo.document?.modelContext ?? alvo.navigator?.modelContext;
  if (!mc || typeof mc.registerTool !== "function") {
    return "Ferramentas WebMCP: este navegador não oferece WebMCP (document.modelContext). Use a tela ou window.delphiContrato.";
  }
  const nomes = [];
  for (const f of ferramentas(api)) {
    try {
      const r = mc.registerTool(f);
      if (r && typeof r.catch === "function") r.catch(() => {});
      nomes.push(f.name);
    } catch {
      // Versão do rascunho com outra assinatura: a tela continua funcionando.
    }
  }
  return nomes.length
    ? `Ferramentas WebMCP registradas: ${nomes.join(", ")}.`
    : "Ferramentas WebMCP: o navegador recusou o registro. Use a tela ou window.delphiContrato.";
}
