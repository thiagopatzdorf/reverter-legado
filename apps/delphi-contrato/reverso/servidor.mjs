// Sessão REA (MCP stdio) que fica aberta: o Ghidra importa o alvo uma vez e responde a pedidos
// deixados em /w/fila/*.json ({"tool": nome, "arguments": {...}}); resposta em /w/resp/<mesmo nome>.
// Encerra sozinha após OCIOSO ms sem pedido: container descartável não fica esquecido ligado.
import { spawn } from "node:child_process";
import { readdirSync, readFileSync, writeFileSync, renameSync, mkdirSync } from "node:fs";
const OCIOSO = 45 * 60 * 1000;
const rea = spawn("rea", ["mcp"], { stdio: ["pipe", "pipe", "inherit"] });
let buf = "", id = 0, ultimo = Date.now();
const pend = new Map();
rea.stdout.on("data", (b) => { buf += b; let i; while ((i = buf.indexOf("\n")) >= 0) { const l = buf.slice(0, i); buf = buf.slice(i + 1); if (!l.trim()) continue; const m = JSON.parse(l); if (m.id != null && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } } });
const chamar = (method, params) => new Promise((ok) => { const n = ++id; pend.set(n, ok); rea.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: n, method, params }) + "\n"); });
await chamar("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "fabrica-reverso", version: "1" } });
rea.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
mkdirSync("/w/feito", { recursive: true });
for (;;) {
  const nomes = readdirSync("/w/fila").filter((n) => n.endsWith(".json")).sort();
  for (const n of nomes) {
    const p = JSON.parse(readFileSync(`/w/fila/${n}`, "utf8"));
    renameSync(`/w/fila/${n}`, `/w/feito/${n}`);
    const t0 = Date.now();
    const r = await chamar("tools/call", { name: p.tool, arguments: p.arguments || {} });
    writeFileSync(`/w/resp/${n}`, JSON.stringify({ segundos: (Date.now() - t0) / 1000, ...r }));
    ultimo = Date.now();
  }
  if (Date.now() - ultimo > OCIOSO) break;
  await new Promise((ok) => setTimeout(ok, 1000));
}
rea.kill();
