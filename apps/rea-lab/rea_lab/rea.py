"""Os comandos do REA de um caso, em lista fechada, e o contêiner onde eles rodam.

O REA (github.com/morluto/rea, MIT) é ferramenta externa: versão fixada, sempre
dentro de um contêiner sem rede, alvo montado só para leitura, e um Ghidra por
vez na máquina (a trava é de quem chama). Nada aqui monta comando a partir de
texto livre: os passos vêm do caso (`caso.json`), e cada argumento é conferido.
"""
from __future__ import annotations

import re

PACOTE = "rea-agents"
# Mesma versão do `delphi_contrato.rea` e da fita (papel `reverso`); o teste reprova se divergirem.
VERSAO_REA = "6.7.0"
IMAGEM = f"rea-local:{VERSAO_REA}"

# Comandos de leitura que o laboratório usa. Nenhum executa o alvo nem fala com a rede.
COMANDOS_PERMITIDOS = {"analyze", "search", "decompile", "function", "xrefs", "trace",
                       "inspect-analysis-view", "inspect-pe-resources", "inspect-binary-layout"}
_ARG_SEGURO = re.compile(r"^[A-Za-z0-9_@.:/=,+\-\[\]%* ]{1,200}$")


def conteiner(nome: str, alvo_dir: str, saida_dir: str) -> list[str]:
    """argv do `docker run` que segura a sessão: sem rede, alvo :ro, 2 CPUs e 8 GB."""
    if not nome.startswith("rj-"):
        raise ValueError("contêiner do laboratório começa com rj- (é o prefixo que a limpeza procura)")
    return ["docker", "run", "-d", "--name", nome, "--network", "none", "--cpus", "2", "--memory", "8g",
            "-e", "REA_GHIDRA_STARTUP_TIMEOUT_MS=7200000",
            "-v", f"{alvo_dir}:/alvo:ro", "-v", f"{saida_dir}:/saida", IMAGEM, "sleep", "86400"]


def passo(nome_conteiner: str, comando: str, args: list[str]) -> list[str]:
    """argv do `docker exec` de um comando do REA, com saída JSON e envelope completo."""
    if comando not in COMANDOS_PERMITIDOS:
        raise ValueError(f"comando do REA fora da lista do laboratório: {comando}")
    for a in args:
        if not _ARG_SEGURO.match(a):
            raise ValueError(f"argumento recusado: {a!r}")
    return ["docker", "exec", nome_conteiner, "rea", comando, *args, "--format", "json", "--full-output"]
