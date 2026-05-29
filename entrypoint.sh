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

# media-editor: ffmpeg envelopado em tools + Backblaze B2 (S3-compatible) como
# storage canonico de seeds e derivacoes. Consumido pelo agente Criativo.
if [ -z "${B2_BUCKET:-}" ] || [ -z "${B2_KEY_ID:-}" ] || [ -z "${B2_APP_KEY:-}" ]; then
  echo "[entrypoint] AVISO: B2_BUCKET/B2_KEY_ID/B2_APP_KEY vazios — media-editor MCP vai recusar operacoes. Configure no .env."
fi
register_mcp media-editor "{\"command\":\"/opt/middleware-venv/bin/python\",\"args\":[\"/app/middleware/media_editor_mcp.py\"],\"env\":{\"B2_KEY_ID\":\"${B2_KEY_ID:-}\",\"B2_APP_KEY\":\"${B2_APP_KEY:-}\",\"B2_BUCKET\":\"${B2_BUCKET:-}\",\"B2_ENDPOINT_URL\":\"${B2_ENDPOINT_URL:-}\"}}"

# whatsapp: envia mensagens via Evolution Go (whatsmeow), que roda como servico
# separado no compose. O middleware alcanca a API em http://evolution-go:8080
# (DNS de servico do compose). EVOLUTION_API_KEY = global (admin/create);
# EVOLUTION_INSTANCE_TOKEN = token da instancia (send/qr/status).
if [ -z "${EVOLUTION_API_KEY:-}" ]; then
  echo "[entrypoint] AVISO: EVOLUTION_API_KEY vazio — whatsapp MCP vai falhar. Configure no .env."
fi
register_mcp whatsapp "{\"command\":\"/opt/middleware-venv/bin/python\",\"args\":[\"/app/middleware/whatsapp_evolution_mcp.py\"],\"env\":{\"EVOLUTION_BASE_URL\":\"${EVOLUTION_BASE_URL:-http://evolution-go:8080}\",\"EVOLUTION_API_KEY\":\"${EVOLUTION_API_KEY:-}\",\"EVOLUTION_INSTANCE_TOKEN\":\"${EVOLUTION_INSTANCE_TOKEN:-}\",\"EVOLUTION_INSTANCE\":\"${EVOLUTION_INSTANCE:-vibestack}\"}}"

# Acrescente novos MCP servers aqui no mesmo padrao:
# register_mcp outro-server '{"command":"...","args":[...]}'

# --- Hermes Agent (alternativa ao OpenClaw, no mesmo container) -----------
# Hermes roda ao lado do OpenClaw: api_server OpenAI-compatible na 8642,
# usando os MESMOS middlewares MCP (meta-ads, media-editor). O provider/modelo
# NAO e' configurado aqui de proposito — o usuario edita config.yaml depois
# (persistido no volume), igual faz com o openclaw.json.
HERMES_HOME="${HOME:-/root}/.hermes"
mkdir -p "$HERMES_HOME"

# Registro MCP: faz um merge idempotente em config.yaml, gravando so as
# entradas mcp_servers e preservando qualquer outra chave (model, provider,
# skills...) que o usuario tenha editado. Sem campo 'tools'/'enabled' o Hermes
# habilita todas as tools do server (tools/mcp_tool.py: default enabled=True,
# filtro de tools vazio). Reusa os scripts e o venv do middleware do OpenClaw.
HERMES_HOME="$HERMES_HOME" \
ACCESS_TOKEN="${ACCESS_TOKEN:-}" \
AD_ACCOUNT_ID="${AD_ACCOUNT_ID:-}" \
BUSINESS_ID="${BUSINESS_ID:-}" \
B2_KEY_ID="${B2_KEY_ID:-}" \
B2_APP_KEY="${B2_APP_KEY:-}" \
B2_BUCKET="${B2_BUCKET:-}" \
B2_ENDPOINT_URL="${B2_ENDPOINT_URL:-}" \
EVOLUTION_BASE_URL="${EVOLUTION_BASE_URL:-http://evolution-go:8080}" \
EVOLUTION_API_KEY="${EVOLUTION_API_KEY:-}" \
EVOLUTION_INSTANCE_TOKEN="${EVOLUTION_INSTANCE_TOKEN:-}" \
EVOLUTION_INSTANCE="${EVOLUTION_INSTANCE:-vibestack}" \
HERMES_APPROVALS_MODE="${HERMES_APPROVALS_MODE:-off}" \
/opt/hermes-agent/venv/bin/python - <<'PYEOF'
import os, sys
from pathlib import Path

try:
    import yaml
except Exception as e:  # noqa: BLE001
    print(f"[entrypoint] AVISO: PyYAML indisponivel no venv do Hermes ({e}) — pulei registro MCP")
    sys.exit(0)

home = Path(os.environ.get("HERMES_HOME", "/root/.hermes"))
cfg_path = home / "config.yaml"

cfg = {}
if cfg_path.exists():
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    except Exception as e:  # noqa: BLE001
        print(f"[entrypoint] AVISO: config.yaml do Hermes ilegivel ({e}) — preservando arquivo, abortando merge")
        sys.exit(0)
if not isinstance(cfg, dict):
    cfg = {}

PY = "/opt/middleware-venv/bin/python"
servers = cfg.setdefault("mcp_servers", {})
if not isinstance(servers, dict):
    servers = {}
    cfg["mcp_servers"] = servers

servers["meta-ads"] = {
    "command": PY,
    "args": ["/app/middleware/meta_ads_cli_mcp.py"],
    "env": {
        "ACCESS_TOKEN": os.environ.get("ACCESS_TOKEN", ""),
        "AD_ACCOUNT_ID": os.environ.get("AD_ACCOUNT_ID", ""),
        "BUSINESS_ID": os.environ.get("BUSINESS_ID", ""),
    },
}
servers["media-editor"] = {
    "command": PY,
    "args": ["/app/middleware/media_editor_mcp.py"],
    "env": {
        "B2_KEY_ID": os.environ.get("B2_KEY_ID", ""),
        "B2_APP_KEY": os.environ.get("B2_APP_KEY", ""),
        "B2_BUCKET": os.environ.get("B2_BUCKET", ""),
        "B2_ENDPOINT_URL": os.environ.get("B2_ENDPOINT_URL", ""),
    },
}
servers["whatsapp"] = {
    "command": PY,
    "args": ["/app/middleware/whatsapp_evolution_mcp.py"],
    "env": {
        "EVOLUTION_BASE_URL": os.environ.get("EVOLUTION_BASE_URL", "http://evolution-go:8080"),
        "EVOLUTION_API_KEY": os.environ.get("EVOLUTION_API_KEY", ""),
        "EVOLUTION_INSTANCE_TOKEN": os.environ.get("EVOLUTION_INSTANCE_TOKEN", ""),
        "EVOLUTION_INSTANCE": os.environ.get("EVOLUTION_INSTANCE", "vibestack"),
    },
}

# Aprovacao de comandos: num canal headless (api_server/WhatsApp) NAO ha quem
# responda o prompt de aprovacao -> o agente TRAVA ate o timeout do bridge.
# Definimos approvals.mode (default 'off') pra auto-aprovar. So' grava se a chave
# ainda nao existe, preservando uma escolha do usuario.
approvals = cfg.get("approvals")
if not isinstance(approvals, dict):
    approvals = {}
    cfg["approvals"] = approvals
approvals.setdefault("mode", os.environ.get("HERMES_APPROVALS_MODE", "off"))

tmp = cfg_path.with_suffix(".yaml.tmp")
tmp.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
tmp.replace(cfg_path)
try:
    cfg_path.chmod(0o600)
except OSError:
    pass
print(f"[entrypoint] hermes mcp 'meta-ads', 'media-editor' e 'whatsapp' registrados em {cfg_path}")
PYEOF

# Sobe o gateway do Hermes em background. A unica plataforma que sobe sem
# token e' o api_server (is_configured=True), e ele EXIGE API_SERVER_KEY pra
# iniciar. Bind interno 0.0.0.0 (Docker publica em loopback no host); a auth
# e' garantida pela API_SERVER_KEY, entao nao precisa de socat (ao contrario do dashboard).
if [ -z "${API_SERVER_KEY:-}" ]; then
  echo "[entrypoint] AVISO: API_SERVER_KEY vazio — Hermes api_server NAO vai subir. Defina HERMES_API_SERVER_KEY no .env."
else
  (
    HERMES_HOME="$HERMES_HOME" \
    API_SERVER_HOST=0.0.0.0 \
    API_SERVER_PORT="${HERMES_API_PORT:-8642}" \
      hermes gateway
  ) >/var/log/hermes.log 2>&1 &
  HERMES_PID=$!
  echo "[entrypoint] hermes gateway iniciado em 0.0.0.0:${HERMES_API_PORT:-8642} (pid=$HERMES_PID, log=/var/log/hermes.log)"
  echo "[entrypoint] LEMBRE: configure o provider/modelo do Hermes (docker exec -it <cont> hermes model) — o build nao baka provider."
fi

# Dashboard web do Hermes (Vite/React) — a "pagina web" de gestao/chat.
# IMPORTANTE: bind em 127.0.0.1 (loopback) dentro do container, NAO 0.0.0.0.
# O dashboard tem defesas de DNS-rebinding/Origin/Host no WebSocket que ficam
# rigidas em bind nao-loopback: com 0.0.0.0 a pagina HTTP carrega mas o WS da
# aba Chat e' rejeitado ("WebSocket connection failed"). Em loopback o servidor
# trata a conexao como local/confiavel e o WS passa (a pagina usa o token
# embutido — sem precisar de --insecure). Publicamos via socat (TCP-puro, o
# WebSocket passa transparente).
#
# --tui: habilita a aba "Chat" embutida (PTY que spawna `hermes --tui`); sem ela
# o dashboard so' mostra config/sessoes. O ui-tui ja' vem pre-buildado na imagem.
HERMES_WEB_PUBLIC_PORT="${HERMES_WEB_PORT:-9119}"
HERMES_WEB_INTERNAL_PORT="${HERMES_WEB_INTERNAL_PORT:-9120}"
(
  HERMES_HOME="$HERMES_HOME" \
    hermes dashboard --host 127.0.0.1 --port "$HERMES_WEB_INTERNAL_PORT" --no-open --tui
) >/var/log/hermes-web.log 2>&1 &
HERMES_WEB_PID=$!
echo "[entrypoint] hermes dashboard iniciado em 127.0.0.1:$HERMES_WEB_INTERNAL_PORT (pid=$HERMES_WEB_PID, chat-tab=on, log=/var/log/hermes-web.log)"

socat \
  TCP-LISTEN:"$HERMES_WEB_PUBLIC_PORT",fork,reuseaddr \
  TCP:127.0.0.1:"$HERMES_WEB_INTERNAL_PORT" \
  >/var/log/hermes-web-socat.log 2>&1 &
HERMES_WEB_SOCAT_PID=$!
echo "[entrypoint] socat bridge 0.0.0.0:$HERMES_WEB_PUBLIC_PORT -> 127.0.0.1:$HERMES_WEB_INTERNAL_PORT (pid=$HERMES_WEB_SOCAT_PID)"

# --- Bridge inbound do WhatsApp (Evolution Go webhook -> Hermes -> resposta) ---
# Fecha o "canal": mensagens recebidas no WhatsApp viram prompts pro agente
# Hermes (api_server na 8642), e a resposta volta pelo /send/text do Evolution.
# Escuta em 0.0.0.0:WA_BRIDGE_PORT (so' rede interna do compose); o evolution-go
# aponta o WEBHOOK_URL pra http://openclaw-vibestack:<porta>/webhook.
# O agente que responde e' escolhido por WA_BRIDGE_AGENT (hermes|openclaw):
#  - hermes  -> precisa de API_SERVER_KEY (HTTP no api_server).
#  - openclaw-> usa a CLI `openclaw agent` (nao precisa de key).
# Sobe se houver como responder no WhatsApp (token da instancia) e, no modo
# hermes, a key do api_server. No modo openclaw basta o token da instancia.
WA_BRIDGE_AGENT="${WA_BRIDGE_AGENT:-hermes}"
if [ -n "${EVOLUTION_INSTANCE_TOKEN:-}" ] && { [ "$WA_BRIDGE_AGENT" = "openclaw" ] || [ -n "${API_SERVER_KEY:-}" ]; }; then
  (
    WA_BRIDGE_AGENT="$WA_BRIDGE_AGENT" \
    WA_BRIDGE_PORT="${WA_BRIDGE_PORT:-8765}" \
    WA_BRIDGE_UPSTREAM="${WA_BRIDGE_UPSTREAM:-http://127.0.0.1:${HERMES_API_PORT:-8642}}" \
    WA_BRIDGE_UPSTREAM_KEY="${API_SERVER_KEY:-}" \
    WA_BRIDGE_MODEL="${WA_BRIDGE_MODEL:-hermes-agent}" \
    WA_BRIDGE_OPENCLAW_AGENT="${WA_BRIDGE_OPENCLAW_AGENT:-}" \
    WA_BRIDGE_ALLOWED_NUMBERS="${WA_BRIDGE_ALLOWED_NUMBERS:-}" \
    WA_BRIDGE_UPSTREAM_TIMEOUT="${WA_BRIDGE_UPSTREAM_TIMEOUT:-900}" \
    WA_BRIDGE_ACK_AFTER="${WA_BRIDGE_ACK_AFTER:-20}" \
    WA_BRIDGE_PUBLIC_URL="${WA_BRIDGE_PUBLIC_URL:-http://openclaw-vibestack:${WA_BRIDGE_PORT:-8765}/webhook}" \
    EVOLUTION_BASE_URL="${EVOLUTION_BASE_URL:-http://evolution-go:8080}" \
    EVOLUTION_API_KEY="${EVOLUTION_API_KEY:-}" \
    EVOLUTION_INSTANCE="${EVOLUTION_INSTANCE:-vibestack}" \
    EVOLUTION_INSTANCE_TOKEN="${EVOLUTION_INSTANCE_TOKEN}" \
    EVOLUTION_PROXY_PROTOCOL="${EVOLUTION_PROXY_PROTOCOL:-http}" \
    EVOLUTION_PROXY_HOST="${EVOLUTION_PROXY_HOST:-}" \
    EVOLUTION_PROXY_PORT="${EVOLUTION_PROXY_PORT:-}" \
    EVOLUTION_PROXY_USERNAME="${EVOLUTION_PROXY_USERNAME:-}" \
    EVOLUTION_PROXY_PASSWORD="${EVOLUTION_PROXY_PASSWORD:-}" \
      /opt/middleware-venv/bin/python /app/middleware/whatsapp_bridge.py
  ) >/var/log/whatsapp-bridge.log 2>&1 &
  WA_BRIDGE_PID=$!
  echo "[entrypoint] whatsapp bridge iniciado em 0.0.0.0:${WA_BRIDGE_PORT:-8765} (agente=$WA_BRIDGE_AGENT, pid=$WA_BRIDGE_PID, log=/var/log/whatsapp-bridge.log)"
else
  echo "[entrypoint] whatsapp bridge NAO subiu (faltou EVOLUTION_INSTANCE_TOKEN, ou API_SERVER_KEY no modo hermes) — canal inbound desligado, envio via MCP segue ok."
fi

exec "$@"
