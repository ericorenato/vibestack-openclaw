#!/bin/sh
# Entrypoint:
#  1) Sobe ollama serve em background.
#  2) Registra MCP servers via `openclaw mcp set` (idempotente, valida schema).
#  3) Executa o comando principal (compose passa 'openclaw gateway ...').
set -e

# --- Ollama em background --------------------------------------------------
ollama serve >/var/log/ollama.log 2>&1 &
OLLAMA_PID=$!

for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "[entrypoint] ollama pronto (pid=$OLLAMA_PID)"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "[entrypoint] AVISO: ollama nao respondeu em 30s — seguindo mesmo assim"
  fi
  sleep 1
done

# --- Registro de MCP servers (Infrastructure as Code via CLI) -------------
# Usa 'openclaw mcp set' que valida schema e grava em mcp.servers.{nome}.
# Idempotente — pode rodar a cada boot. Se openclaw.json nao existir, o
# wizard de configuracao do openclaw precisa rodar antes (uma vez por VPS).
register_mcp() {
  name="$1"
  json="$2"
  if openclaw mcp set "$name" "$json" >/dev/null 2>&1; then
    echo "[entrypoint] mcp '$name' registrado"
  else
    echo "[entrypoint] AVISO: falha ao registrar mcp '$name' (openclaw.json ausente? rode 'openclaw configure' uma vez)"
  fi
}

# Tokens da Meta CLI: o openclaw spawna o MCP child com env reduzido, entao
# repassamos ACCESS_TOKEN/AD_ACCOUNT_ID/BUSINESS_ID explicitamente. Sem isso o
# subprocesso 'meta' devolve "No access token found" / "No ad account configured".
if [ -z "${ACCESS_TOKEN:-}" ]; then
  echo "[entrypoint] AVISO: ACCESS_TOKEN vazio — meta-ads MCP vai falhar auth. Verifique META_ACCESS_TOKEN no .env."
fi

# CLI exige 'act_' no AD_ACCOUNT_ID (ex: act_123456). Adiciona se faltar.
case "${AD_ACCOUNT_ID:-}" in
  ""|act_*) ;;
  *) AD_ACCOUNT_ID="act_${AD_ACCOUNT_ID}" ;;
esac

register_mcp meta-ads "{\"command\":\"/opt/middleware-venv/bin/python\",\"args\":[\"/app/middleware/meta_ads_cli_mcp.py\"],\"env\":{\"ACCESS_TOKEN\":\"${ACCESS_TOKEN:-}\",\"AD_ACCOUNT_ID\":\"${AD_ACCOUNT_ID:-}\",\"BUSINESS_ID\":\"${BUSINESS_ID:-}\"}}"

# Acrescente novos MCP servers aqui no mesmo padrao:
# register_mcp outro-server '{"command":"...","args":[...]}'

# --- Pixel Agents Dashboard em background ---------------------------------
# Visualizer pixel-art dos agentes OpenClaw. Le JSONL em ~/.openclaw/agents/
# e fala com o gateway in-process via http://localhost:18789.
#
# Roda com cwd=$PIXEL_AGENTS_DATA: configLoader le dashboard.config.json
# do cwd (depois de PIXEL_AGENTS_CONFIG, antes do XDG), e o setupWizard grava
# em `path.resolve(CONFIG_FILENAME)` (tambem cwd). Sem config ali, o wizard
# fica acessivel em http://localhost:5070 — auto-discover dos agentes em
# /root/.openclaw/agents, escolha de features e teste do gateway.
#
# Apos salvar pelo wizard, o processo faz exit(0) esperando supervisor; o
# loop abaixo recoloca de pe em 2s.
PIXEL_AGENTS_DATA=/root/.openclaw/pixel-agents
mkdir -p "$PIXEL_AGENTS_DATA/data"

# Layout dos sprites persistido no volume via symlink.
rm -rf /opt/pixel-agents-dashboard/data 2>/dev/null || true
ln -sfn "$PIXEL_AGENTS_DATA/data" /opt/pixel-agents-dashboard/data

(
  cd "$PIXEL_AGENTS_DATA"
  while true; do
    PIXEL_AGENTS_ROOT=/opt/pixel-agents-dashboard \
    PIXEL_AGENTS_PORT="${PIXEL_AGENTS_PORT:-5070}" \
    NODE_ENV=production \
      /opt/pixel-agents-dashboard/node_modules/.bin/tsx \
      /opt/pixel-agents-dashboard/server/index.ts
    echo "[entrypoint] pixel-agents exited (likely wizard save) — restart in 2s"
    sleep 2
  done
) >/var/log/pixel-agents.log 2>&1 &
PIXEL_PID=$!
echo "[entrypoint] pixel-agents-dashboard iniciado (pid=$PIXEL_PID, log=/var/log/pixel-agents.log)"

exec "$@"
