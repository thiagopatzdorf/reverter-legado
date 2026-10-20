# Receita do contêiner do REA (papel `reverso`)

A imagem `rea-local:6.7.0` foi montada à mão na factory-01 em 2026-10-19 para os casos
HeidiSQL (`casos/heidisql_rea.py`) e Chocolate Doom (`apps/rea-lab`). Esta é a receita para
levantar de novo, guardada aqui antes de a imagem e a pasta de trabalho serem apagadas.

A receita fica em texto, sem um `Dockerfile` no repo: arquivo `Dockerfile*` é risco alto
(`AGENTS.md` §5), e nada aqui é construído pelo CI. Para usar, copie o bloco abaixo para
`ctx/Dockerfile` numa pasta de trabalho fora do repo.

## Entradas (versão e sha256 fixos)

| arquivo | origem | sha256 |
|---|---|---|
| `node-v22.22.0-linux-x64.tar.xz` | https://nodejs.org/dist/v22.22.0/node-v22.22.0-linux-x64.tar.xz | `9aa8e9d2298ab68c600bd6fb86a6c13bce11a4eca1ba9b39d79fa021755d7c37` |
| `ghidra_12.1.4_PUBLIC_20260921.zip` | https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip | `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db` |
| `rea-agents` | npm, `rea-agents@6.7.0` (MIT), instalado com `--ignore-scripts` | versão fixada no código (`delphi_contrato/rea.py`) e na fita |

Baixe os dois arquivos, confira com `sha256sum -c` e extraia o Ghidra para
`ctx/ghidra_12.1.4_PUBLIC`. O zip perde o bit de execução: rode `chmod +x` nos `*.sh`, em
`analyzeHeadless`, `ghidraRun`, `launch.sh`, `decompile` e `sleigh`.

## A imagem

```dockerfile
# REA (rea-agents 6.7.0, MIT) + Ghidra 12.1.4 + JDK 21 + Node 22, para ler executável de terceiros
# sem rede, sem segredo e sem root. Imagem descartável do papel `reverso` (factory.manifest.json).
FROM eclipse-temurin:21-jdk-noble
RUN apt-get update && apt-get install -y --no-install-recommends procps xz-utils ca-certificates && rm -rf /var/lib/apt/lists/*
COPY node-v22.22.0-linux-x64.tar.xz /tmp/
RUN tar -xJf /tmp/node-v22.22.0-linux-x64.tar.xz -C /opt && rm /tmp/node-v22.22.0-linux-x64.tar.xz \
 && ln -s /opt/node-v22.22.0-linux-x64/bin/node /usr/local/bin/node && ln -s /opt/node-v22.22.0-linux-x64/bin/npm /usr/local/bin/npm \
 && ln -s /opt/node-v22.22.0-linux-x64/bin/npx /usr/local/bin/npx
COPY ghidra_12.1.4_PUBLIC /opt/ghidra
RUN npm install -g --ignore-scripts rea-agents@6.7.0 && ln -sf /opt/node-v22.22.0-linux-x64/bin/rea /usr/local/bin/rea || true
RUN useradd -m rea && mkdir -p /saida && chown rea /saida
ENV GHIDRA_INSTALL_DIR=/opt/ghidra JAVA_HOME=/opt/java/openjdk
USER rea
WORKDIR /saida
```

    docker build -q -t rea-local:6.7.0 ctx
    docker run --rm --network none rea-local:6.7.0 sh -c 'node --version; rea --version; ls /opt/ghidra/support/analyzeHeadless'

A imagem fica com 2,84 GB.

## A sessão (`servidor.mjs`)

O `rea` pela CLI reimporta o binário a cada comando. Em modo MCP, o Ghidra importa uma vez e
cada pergunta depois leva menos de 1 s. O `servidor.mjs` deixa essa sessão aberta e lê
pedidos de uma fila em disco, então quem pergunta não precisa manter conexão:

    mkdir -p "$REA_DIR"/alvo "$REA_DIR"/fila "$REA_DIR"/resp && cp servidor.mjs "$REA_DIR"/
    cp <executável> "$REA_DIR"/alvo/
    echo '{"tool":"open_binary","arguments":{"path":"/alvo/<executável>","provider_id":"ghidra"}}' > "$REA_DIR"/fila/00-abrir.json
    docker run -d --name rea-sessao --network none --cpus 3.5 --memory 26g \
      -e REA_GHIDRA_STARTUP_TIMEOUT_MS=7200000 \
      -v "$REA_DIR"/alvo:/alvo:ro -v "$REA_DIR":/w rea-local:6.7.0 node /w/servidor.mjs

- **Pedido:** um JSON por arquivo em `fila/`, no formato `{"tool": ..., "arguments": {...}}`.
  Escreva o arquivo fora da fila e mova para lá (`mv`), para o servidor nunca ler um arquivo
  pela metade.
- **Resposta:** sai em `resp/` com o mesmo nome e o tempo em `segundos`.
- **Fim da sessão:** ela encerra sozinha depois de 45 min sem pedido.

Na primeira pergunta de análise (`binary_overview`) o Ghidra faz a análise completa: 1.053 s
para o `heidisql.exe` (25 MB) numa `e2-highmem-4` e 134 s para o `chocolate-doom.exe`.

## Limpeza

- Derrube o contêiner com `docker rm -f rea-sessao`.
- Copie a evidência de `resp/` e `feito/` para pastas **separadas**: os nomes são os mesmos,
  e numa pasta só o pedido sobrescreve a resposta.
- Só depois disso apague a pasta. A imagem sai com `docker rmi rea-local:6.7.0`.
