#!/bin/sh
# Entrypoint:
#  1) Sobe os backends de modelos locais INSTALADOS na imagem (Ollama e/ou LM Studio).
#  2) Registra MCP servers via `openclaw mcp set` (idempotente, valida schema).
#  3) Executa o comando principal (compose passa 'openclaw gateway ...').
set -e

# --- Plataformas de agente instaladas (build args -> env) ------------------
# O ./install.sh pergunta qual plataforma instalar (OpenClaw / Hermes / ambas)
# e grava INSTALL_OPENCLAW / INSTALL_HERMES. O que nao foi instalado nem entra
# na imagem (o Dockerfile pula o build) nem sobe aqui.
INSTALL_OPENCLAW="${INSTALL_OPENCLAW:-true}"
INSTALL_HERMES="${INSTALL_HERMES:-true}"

# Coerencia do agente que responde o WhatsApp com o que foi instalado: se so'
# uma plataforma existe, o bridge tem que apontar pra ela (senao 'hermes' default
# tentaria um gateway inexistente).
if [ "$INSTALL_HERMES" != "true" ]; then WA_BRIDGE_AGENT=openclaw; fi
if [ "$INSTALL_OPENCLAW" != "true" ]; then WA_BRIDGE_AGENT=hermes; fi

# --- Backends de modelos locais (sobe o que estiver instalado) -------------
# O ./install.sh decide o que entra na imagem (build args INSTALL_OLLAMA /
# INSTALL_LMSTUDIO). Aqui apenas detectamos o que foi baixado e subimos cada um:
#   - Ollama    -> porta 11434 (comportamento de sempre).
#   - LM Studio -> daemon llmster + server OpenAI-compat na 1234.
# Portas distintas: se ambos estiverem instalados, sobem os dois sem conflito.
# Os helpers (start-ollama / start-lmstudio) sao idempotentes e tambem servem
# para (re)start manual via `docker compose exec`. Rodam em BACKGROUND para nao
# bloquear o boot do gateway — o LM Studio pode levar 1-2 min no 1o uso (extracao
# do runtime). set -e desligado em volta para que a falha de um nao derrube o boot.
set +e
if command -v ollama >/dev/null 2>&1; then start-ollama & fi
if command -v lms >/dev/null 2>&1; then start-lmstudio & fi
set -e

# --- Registro de MCP servers (Infrastructure as Code via CLI) -------------
# Usa 'openclaw mcp set' que valida schema e grava em mcp.servers.{nome}.
# Idempotente — pode rodar a cada boot. Se openclaw.json nao existir, o
# wizard de configuracao do openclaw precisa rodar antes (uma vez por VPS).
register_mcp() {
  name="$1"
  json="$2"
  # So' registra no OpenClaw se ele estiver instalado (senao nao ha' binario
  # `openclaw`). O Hermes tem seu proprio registro (config.yaml) mais abaixo.
  [ "$INSTALL_OPENCLAW" = "true" ] || return 0
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

# Google Ads: MCP sobre o SDK oficial (google-ads). Auth OAuth2 lida pelo
# load_from_env() -> repassamos as GOOGLE_ADS_* explicitamente (env reduzido no
# spawn do child). Sem refresh_token as tools devolvem erro (nao derruba o boot).
if [ -z "${GOOGLE_ADS_DEVELOPER_TOKEN:-}" ] || [ -z "${GOOGLE_ADS_REFRESH_TOKEN:-}" ]; then
  echo "[entrypoint] AVISO: GOOGLE_ADS_DEVELOPER_TOKEN/REFRESH_TOKEN vazio — google-ads MCP vai falhar auth. Rode 'googleads auth' e preencha o .env."
fi
register_mcp google-ads "{\"command\":\"/opt/middleware-venv/bin/python\",\"args\":[\"/app/middleware/google_ads_cli_mcp.py\"],\"env\":{\"GOOGLE_ADS_DEVELOPER_TOKEN\":\"${GOOGLE_ADS_DEVELOPER_TOKEN:-}\",\"GOOGLE_ADS_CLIENT_ID\":\"${GOOGLE_ADS_CLIENT_ID:-}\",\"GOOGLE_ADS_CLIENT_SECRET\":\"${GOOGLE_ADS_CLIENT_SECRET:-}\",\"GOOGLE_ADS_REFRESH_TOKEN\":\"${GOOGLE_ADS_REFRESH_TOKEN:-}\",\"GOOGLE_ADS_LOGIN_CUSTOMER_ID\":\"${GOOGLE_ADS_LOGIN_CUSTOMER_ID:-}\",\"GOOGLE_ADS_CUSTOMER_ID\":\"${GOOGLE_ADS_CUSTOMER_ID:-}\",\"GOOGLE_ADS_USE_PROTO_PLUS\":\"True\"}}"

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

# higgsfield: envelopa o CLI 'higgsfield' (geracao de imagem/video, soul-id) como
# tools tipados. O CLI le o token de ~/.higgsfield -> passamos HOME=/root explicito
# porque o openclaw spawna o MCP child com env reduzido. Auth: o aluno roda uma vez
# `docker exec -it <cont> higgsfield auth login` (OAuth no navegador); o token fica
# no volume /root/.higgsfield e sobrevive a restart/rebuild.
register_mcp higgsfield "{\"command\":\"/opt/middleware-venv/bin/python\",\"args\":[\"/app/middleware/higgsfield_cli_mcp.py\"],\"env\":{\"HOME\":\"/root\"}}"

# atlascloud: MCP server OFICIAL da AtlasCloud (hub de 300+ modelos img/video/LLM).
# Instalado global na imagem (bin /usr/local/bin/atlascloud-mcp). Auth so' por env
# ATLASCLOUD_API_KEY — repassada explicitamente porque o openclaw spawna o child
# com env reduzido. Sem login nem volume: a chave no .env ja' sobrevive a restart.
if [ -z "${ATLASCLOUD_API_KEY:-}" ]; then
  echo "[entrypoint] AVISO: ATLASCLOUD_API_KEY vazio — atlascloud MCP vai falhar auth. Configure no .env."
fi
register_mcp atlascloud "{\"command\":\"/usr/local/bin/atlascloud-mcp\",\"args\":[],\"env\":{\"ATLASCLOUD_API_KEY\":\"${ATLASCLOUD_API_KEY:-}\"}}"

# Acrescente novos MCP servers aqui no mesmo padrao:
# register_mcp outro-server '{"command":"...","args":[...]}'

# Diretorio persistente de assets dos agentes (dentro do volume /root/.openclaw).
# Mídia gerada/baixada (ex.: pelo higgsfield MCP) vai pra ca' e sobrevive a restart.
# Qualquer escrita fora de /root/.openclaw (/tmp, /app, cwd) e' efemera.
mkdir -p /root/.openclaw/workspace/_shared/assets /root/.openclaw/workspace/_shared/creatives 2>/dev/null || true

# --- Hermes Agent (alternativa ao OpenClaw, no mesmo container) -----------
# Hermes roda ao lado do OpenClaw: api_server OpenAI-compatible na 8642,
# usando os MESMOS middlewares MCP (meta-ads, media-editor). O provider/modelo
# NAO e' configurado aqui de proposito — o usuario edita config.yaml depois
# (persistido no volume), igual faz com o openclaw.json.
if [ "$INSTALL_HERMES" = "true" ]; then
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
GOOGLE_ADS_DEVELOPER_TOKEN="${GOOGLE_ADS_DEVELOPER_TOKEN:-}" \
GOOGLE_ADS_CLIENT_ID="${GOOGLE_ADS_CLIENT_ID:-}" \
GOOGLE_ADS_CLIENT_SECRET="${GOOGLE_ADS_CLIENT_SECRET:-}" \
GOOGLE_ADS_REFRESH_TOKEN="${GOOGLE_ADS_REFRESH_TOKEN:-}" \
GOOGLE_ADS_LOGIN_CUSTOMER_ID="${GOOGLE_ADS_LOGIN_CUSTOMER_ID:-}" \
GOOGLE_ADS_CUSTOMER_ID="${GOOGLE_ADS_CUSTOMER_ID:-}" \
ATLASCLOUD_API_KEY="${ATLASCLOUD_API_KEY:-}" \
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
servers["google-ads"] = {
    "command": PY,
    "args": ["/app/middleware/google_ads_cli_mcp.py"],
    "env": {
        "GOOGLE_ADS_DEVELOPER_TOKEN": os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", ""),
        "GOOGLE_ADS_CLIENT_ID": os.environ.get("GOOGLE_ADS_CLIENT_ID", ""),
        "GOOGLE_ADS_CLIENT_SECRET": os.environ.get("GOOGLE_ADS_CLIENT_SECRET", ""),
        "GOOGLE_ADS_REFRESH_TOKEN": os.environ.get("GOOGLE_ADS_REFRESH_TOKEN", ""),
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID", ""),
        "GOOGLE_ADS_CUSTOMER_ID": os.environ.get("GOOGLE_ADS_CUSTOMER_ID", ""),
        "GOOGLE_ADS_USE_PROTO_PLUS": "True",
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
servers["higgsfield"] = {
    "command": PY,
    "args": ["/app/middleware/higgsfield_cli_mcp.py"],
    # CLI le o token de ~/.higgsfield -> HOME explicito (env reduzido no spawn).
    "env": {"HOME": "/root"},
}
servers["atlascloud"] = {
    # MCP oficial da AtlasCloud, instalado global na imagem. Auth so' por env.
    "command": "/usr/local/bin/atlascloud-mcp",
    "args": [],
    "env": {"ATLASCLOUD_API_KEY": os.environ.get("ATLASCLOUD_API_KEY", "")},
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
print(f"[entrypoint] hermes mcp 'meta-ads', 'google-ads', 'media-editor' e 'whatsapp' registrados em {cfg_path}")
PYEOF

# Sobe o gateway do Hermes em background. A unica plataforma que sobe sem
# token e' o api_server (is_configured=True), e ele EXIGE API_SERVER_KEY pra
# iniciar. Bind interno 0.0.0.0 (Docker publica em loopback no host); a auth
# e' garantida pela API_SERVER_KEY, entao nao precisa de socat (ao contrario do dashboard).
#
# IMPORTANTE: usar 'hermes gateway RUN' (foreground, recomendado p/ Docker) — NAO
# 'hermes gateway' sozinho nem 'start' (que e' pra servico systemd/launchd e se
# recusa dentro de container). O 'run' e' quem roda o loop do gateway COM o
# dispatcher embutido do Kanban (tick de 60s). Sem ele, as tasks ficam presas em
# 'ready' e o 'hermes gateway status' reporta "not running".
#
# Como aqui o processo PRINCIPAL do container e' o OpenClaw (nao o Hermes), o
# gateway do Hermes nao tem supervisor: se cair, ninguem reergue. Por isso o
# envolvemos num laco de AUTO-RESTART (reinicia em 5s se sair). HERMES_ACCEPT_HOOKS=1
# evita travar num prompt de hook sem TTY (canal headless, igual approvals=off).
# Gateway do Hermes em BACKGROUND — so' quando o OpenClaw e' o processo principal
# do container. No modo Hermes-only ele sobe em FOREGROUND no final (exec).
if [ "$INSTALL_OPENCLAW" = "true" ]; then
if [ -z "${API_SERVER_KEY:-}" ]; then
  echo "[entrypoint] AVISO: API_SERVER_KEY vazio — Hermes api_server NAO vai subir. Defina HERMES_API_SERVER_KEY no .env."
else
  # -p default: FIXA o gateway no profile 'default'. Sem isso, o gateway sobe sob
  # o profile ATIVO no boot — e se alguem deu 'hermes profile use <cargo>' antes de
  # reiniciar, o gateway (e o api_server 8642) subiria sob o profile errado, e
  # 'hermes gateway status' (no profile default) acusaria "not running". O board do
  # Kanban e' compartilhado (/root/.hermes/kanban.db), entao um unico gateway default
  # ja' despacha tasks de QUALQUER assignee (spawna o profile de cada task).
  HERMES_GATEWAY_PROFILE="${HERMES_GATEWAY_PROFILE:-default}"
  (
    while true; do
      HERMES_HOME="$HERMES_HOME" \
      API_SERVER_HOST=0.0.0.0 \
      API_SERVER_PORT="${HERMES_API_PORT:-8642}" \
      HERMES_ACCEPT_HOOKS=1 \
        hermes -p "$HERMES_GATEWAY_PROFILE" gateway run
      echo "[entrypoint] AVISO: 'hermes gateway run' (profile=$HERMES_GATEWAY_PROFILE) saiu (code $?) — reiniciando em 5s"
      sleep 5
    done
  ) >/var/log/hermes.log 2>&1 &
  HERMES_PID=$!
  echo "[entrypoint] hermes gateway run (auto-restart) iniciado em 0.0.0.0:${HERMES_API_PORT:-8642} (pid=$HERMES_PID, log=/var/log/hermes.log)"
  echo "[entrypoint] LEMBRE: configure o provider/modelo do Hermes (docker exec -it <cont> hermes model) — o build nao baka provider."
fi
fi   # fim do gateway-em-background (so' com OpenClaw como principal)

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
fi   # fim do bloco Hermes (INSTALL_HERMES=true)

# --- Bridge inbound do WhatsApp (Evolution Go webhook -> agente -> resposta) ---
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
    WA_BRIDGE_UPSTREAM_TIMEOUT="${WA_BRIDGE_UPSTREAM_TIMEOUT:-0}" \
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
    EVOLUTION_IGNORE_GROUPS="${EVOLUTION_IGNORE_GROUPS:-true}" \
    EVOLUTION_IGNORE_STATUS="${EVOLUTION_IGNORE_STATUS:-true}" \
      /opt/middleware-venv/bin/python /app/middleware/whatsapp_bridge.py
  ) >/var/log/whatsapp-bridge.log 2>&1 &
  WA_BRIDGE_PID=$!
  echo "[entrypoint] whatsapp bridge iniciado em 0.0.0.0:${WA_BRIDGE_PORT:-8765} (agente=$WA_BRIDGE_AGENT, pid=$WA_BRIDGE_PID, log=/var/log/whatsapp-bridge.log)"
else
  echo "[entrypoint] whatsapp bridge NAO subiu (faltou EVOLUTION_INSTANCE_TOKEN, ou API_SERVER_KEY no modo hermes) — canal inbound desligado, envio via MCP segue ok."
fi

# --- Patch: timeout de publicacao do "prepared model runtime" -------------
# O OpenClaw 2026.7.x traz DEFAULT_MODEL_RUNTIME_BUILD_TIMEOUT_MS = 3e4 (30s)
# hardcoded no bundle e NAO le nenhuma env pra isso. Com varios agentes
# (openclaw agents add) o build/publish de cada runtime passa de 30s — sobretudo
# em Docker Desktop/WSL — e o gateway morre com:
#   prepared model runtime publication timed out
# ...antes de chegar em "[gateway] ready", escondendo todos os agentes da TUI.
# Reescrevemos a constante no dist a cada boot (o dist vive na imagem, nao em
# volume, entao o patch some no rebuild e e' reaplicado aqui). So' faz sentido
# quando o OpenClaw esta' instalado (e' quem tem /app/dist).
patch_model_runtime_timeout() {
  ms="${OPENCLAW_MODEL_RUNTIME_BUILD_TIMEOUT_MS:-120000}"
  case "$ms" in
    ''|*[!0-9]*)
      echo "[entrypoint] AVISO: OPENCLAW_MODEL_RUNTIME_BUILD_TIMEOUT_MS='$ms' nao e' inteiro — patch ignorado"
      return 0 ;;
  esac

  # Chunk com nome hasheado (prepared-model-runtime-XXXX.js). Se o hash mudar de
  # versao e o glob falhar, cai no grep pelo simbolo em todo o dist.
  files=""
  for f in /app/dist/prepared-model-runtime-*.js; do
    [ -f "$f" ] && files="${files} $f"
  done
  if [ -z "$files" ]; then
    files="$(grep -rl 'DEFAULT_MODEL_RUNTIME_BUILD_TIMEOUT_MS' /app/dist 2>/dev/null || true)"
  fi
  if [ -z "$files" ]; then
    echo "[entrypoint] AVISO: DEFAULT_MODEL_RUNTIME_BUILD_TIMEOUT_MS nao encontrado no /app/dist — upstream mudou? patch pulado"
    return 0
  fi

  for f in $files; do
    grep -q 'DEFAULT_MODEL_RUNTIME_BUILD_TIMEOUT_MS' "$f" 2>/dev/null || continue
    if grep -qE "DEFAULT_MODEL_RUNTIME_BUILD_TIMEOUT_MS[[:space:]]*=[[:space:]]*${ms}[;,]" "$f"; then
      echo "[entrypoint] model runtime timeout ja' em ${ms}ms ($f)"
      continue
    fi
    if sed -i -E "s/(DEFAULT_MODEL_RUNTIME_BUILD_TIMEOUT_MS[[:space:]]*=[[:space:]]*)[0-9]+(\.[0-9]+)?([eE]\+?[0-9]+)?/\1${ms}/" "$f" 2>/dev/null; then
      echo "[entrypoint] model runtime timeout -> ${ms}ms ($f)"
    else
      echo "[entrypoint] AVISO: falha ao patchar $f (readonly?) — gateway pode falhar com varios agentes"
    fi
  done
}
[ "$INSTALL_OPENCLAW" = "true" ] && { patch_model_runtime_timeout || true; }

# --- Processo principal do container ---------------------------------------
# OpenClaw instalado -> ele e' o foreground (exec do CMD do compose:
# 'openclaw gateway ...'). Hermes-only -> o gateway do Hermes vira o principal.
if [ "$INSTALL_OPENCLAW" = "true" ]; then
  exec "$@"
elif [ "$INSTALL_HERMES" = "true" ]; then
  if [ -z "${API_SERVER_KEY:-}" ]; then
    echo "[entrypoint] ERRO: API_SERVER_KEY vazio — Hermes api_server nao sobe. Defina HERMES_API_SERVER_KEY no .env."
    exit 1
  fi
  HERMES_GATEWAY_PROFILE="${HERMES_GATEWAY_PROFILE:-default}"
  echo "[entrypoint] hermes gateway run (FOREGROUND, processo principal) em 0.0.0.0:${HERMES_API_PORT:-8642}"
  exec env HERMES_HOME="$HERMES_HOME" \
           API_SERVER_HOST=0.0.0.0 \
           API_SERVER_PORT="${HERMES_API_PORT:-8642}" \
           HERMES_ACCEPT_HOOKS=1 \
           hermes -p "$HERMES_GATEWAY_PROFILE" gateway run
else
  echo "[entrypoint] ERRO: nenhuma plataforma de agente instalada (INSTALL_OPENCLAW/INSTALL_HERMES ambos != true)."
  exit 1
fi
