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

# Acrescente novos MCP servers aqui no mesmo padrao:
# register_mcp outro-server '{"command":"...","args":[...]}'

# --- Claw3D em background -------------------------------------------------
# Visualizador 3D dos agentes OpenClaw. server/index.js sobe o Next.js +
# proxy WebSocket pro gateway. Browser conecta same-origin via /api/gateway/ws.
#
# O modulo studio-settings le gateway URL/token de:
#   1. /root/.openclaw/claw3d/settings.json  (preferido — editavel pelo Studio UI)
#   2. /root/.openclaw/openclaw.json -> gateway.auth.token  (apenas se token e' string)
#
# Como nosso openclaw.json tem token={"source":"env",...} (nao-string), o
# fallback falha. Bootstrap: gera settings.json APENAS no primeiro boot, com
# token resolvido do env. Depois disso, deixa o Studio UI ser a fonte da
# verdade — edicoes feitas na interface persistem entre restarts/rebuilds.
# Pra regenerar do env (ex: token rotacionado): rm settings.json e restart.
CLAW3D_DIR=/root/.openclaw/claw3d
mkdir -p "$CLAW3D_DIR"

if [ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]; then
  echo "[entrypoint] AVISO: OPENCLAW_GATEWAY_TOKEN vazio — Claw3D Studio nao vai autenticar no gateway."
fi

if [ ! -f "$CLAW3D_DIR/settings.json" ]; then
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
  echo "[entrypoint] claw3d settings.json criado em $CLAW3D_DIR (primeiro boot)"
else
  echo "[entrypoint] claw3d settings.json ja existe — preservando edicoes do Studio UI"
fi

# Bind o Claw3D em 127.0.0.1 dentro do container — assim o network-policy
# considera loopback e o access-gate fica desligado (sem cookie/login).
# Depois usamos socat pra expor em 0.0.0.0:CLAW3D_PORT pro Docker publicar.
# Resultado: acesso via SSH tunnel funciona como um servico local, direto.
CLAW3D_INTERNAL_PORT="${CLAW3D_INTERNAL_PORT:-3001}"
CLAW3D_PUBLIC_PORT="${CLAW3D_PORT:-3000}"

(
  cd /opt/claw3d
  NODE_ENV=production \
  NEXT_TELEMETRY_DISABLED=1 \
  HOST=127.0.0.1 \
  PORT="$CLAW3D_INTERNAL_PORT" \
  UPSTREAM_ALLOWLIST="${UPSTREAM_ALLOWLIST:-localhost,127.0.0.1}" \
    node server/index.js
) >/var/log/claw3d.log 2>&1 &
CLAW3D_PID=$!
echo "[entrypoint] claw3d iniciado em 127.0.0.1:$CLAW3D_INTERNAL_PORT (pid=$CLAW3D_PID, log=/var/log/claw3d.log)"

# Bridge socat: 0.0.0.0:PUBLIC -> 127.0.0.1:INTERNAL. fork pra conexoes
# concorrentes, reuseaddr pra restart rapido. socat e' TCP-puro, entao
# WebSocket (que Claw3D usa pro proxy) passa transparente.
socat \
  TCP-LISTEN:"$CLAW3D_PUBLIC_PORT",fork,reuseaddr \
  TCP:127.0.0.1:"$CLAW3D_INTERNAL_PORT" \
  >/var/log/claw3d-socat.log 2>&1 &
SOCAT_PID=$!
echo "[entrypoint] socat bridge 0.0.0.0:$CLAW3D_PUBLIC_PORT -> 127.0.0.1:$CLAW3D_INTERNAL_PORT (pid=$SOCAT_PID)"

# --- Hermes Agent (alternativa ao OpenClaw, no mesmo container) -----------
# Hermes roda ao lado do OpenClaw: api_server OpenAI-compatible na 8642,
# usando os MESMOS middlewares MCP (meta-ads, media-editor). O provider/modelo
# NAO e' configurado aqui de proposito — o usuario edita config.yaml depois
# (persistido no volume), igual faz com o openclaw.json.
HERMES_HOME="${HOME:-/root}/.hermes"
mkdir -p "$HERMES_HOME"

# Registro MCP: faz um merge idempotente em config.yaml, gravando so as duas
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

tmp = cfg_path.with_suffix(".yaml.tmp")
tmp.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
tmp.replace(cfg_path)
try:
    cfg_path.chmod(0o600)
except OSError:
    pass
print(f"[entrypoint] hermes mcp 'meta-ads' e 'media-editor' registrados em {cfg_path}")
PYEOF

# Sobe o gateway do Hermes em background. A unica plataforma que sobe sem
# token e' o api_server (is_configured=True), e ele EXIGE API_SERVER_KEY pra
# iniciar. Bind interno 0.0.0.0 (Docker publica em loopback no host); a auth
# e' garantida pela API_SERVER_KEY, entao nao precisa de socat como o Claw3D.
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
# Bind 0.0.0.0 pra o Docker publicar; --insecure desliga o auth-gate (que e'
# obrigatorio em bind nao-loopback). Como a porta so' e' publicada em
# 127.0.0.1 no host (acesso via SSH tunnel na VPS), seguimos o mesmo modelo
# loopback-sem-gate do Claw3D. Sem --skip-build: usa a UI ja' pre-buildada na
# imagem (o helper do Hermes pula o rebuild quando nao e' necessario).
(
  HERMES_HOME="$HERMES_HOME" \
    hermes dashboard --host 0.0.0.0 --port "${HERMES_WEB_PORT:-9119}" --insecure --no-open
) >/var/log/hermes-web.log 2>&1 &
HERMES_WEB_PID=$!
echo "[entrypoint] hermes dashboard iniciado em 0.0.0.0:${HERMES_WEB_PORT:-9119} (pid=$HERMES_WEB_PID, log=/var/log/hermes-web.log)"

exec "$@"
