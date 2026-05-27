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

# --- Claw3D em background -------------------------------------------------
# Visualizador 3D dos agentes OpenClaw. server/index.js sobe o Next.js +
# proxy WebSocket pro gateway. Browser conecta same-origin via /api/gateway/ws.
#
# O modulo studio-settings le gateway URL/token de:
#   1. /root/.openclaw/claw3d/settings.json  (preferido)
#   2. /root/.openclaw/openclaw.json -> gateway.auth.token  (apenas se token e' string)
#
# Como nosso openclaw.json tem token={"source":"env",...} (nao-string), o
# fallback falha. Geramos settings.json a cada boot com o token resolvido
# do env, mantendo gateway URL/token sempre em sincronia com o .env.
CLAW3D_DIR=/root/.openclaw/claw3d
mkdir -p "$CLAW3D_DIR"

if [ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]; then
  echo "[entrypoint] AVISO: OPENCLAW_GATEWAY_TOKEN vazio — Claw3D Studio nao vai autenticar no gateway."
fi

cat > "$CLAW3D_DIR/settings.json" <<EOF
{
  "gateway": {
    "url": "ws://localhost:${OPENCLAW_GATEWAY_PORT:-18789}",
    "token": "${OPENCLAW_GATEWAY_TOKEN:-}",
    "adapterType": "openclaw"
  }
}
EOF
chmod 600 "$CLAW3D_DIR/settings.json"
echo "[entrypoint] claw3d settings.json regenerado em $CLAW3D_DIR"

(
  cd /opt/claw3d
  NODE_ENV=production \
  NEXT_TELEMETRY_DISABLED=1 \
  HOST="${CLAW3D_HOST:-0.0.0.0}" \
  PORT="${CLAW3D_PORT:-3000}" \
  STUDIO_ACCESS_TOKEN="${STUDIO_ACCESS_TOKEN:-${OPENCLAW_GATEWAY_TOKEN:-}}" \
  UPSTREAM_ALLOWLIST="${UPSTREAM_ALLOWLIST:-localhost,127.0.0.1}" \
    node server/index.js
) >/var/log/claw3d.log 2>&1 &
CLAW3D_PID=$!
echo "[entrypoint] claw3d iniciado (pid=$CLAW3D_PID, log=/var/log/claw3d.log)"

exec "$@"
