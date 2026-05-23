#!/bin/sh
# Entrypoint:
#  1) Seed do openclaw.json a partir do template versionado (first-boot, ou
#     forcado por OPENCLAW_CONFIG_OVERWRITE=true).
#  2) Sobe ollama serve em background.
#  3) Executa o comando principal (compose passa 'openclaw gateway ...').
set -e

# --- Seed do openclaw.json (Infrastructure as Code) -----------------------
TEMPLATE=/opt/openclaw-config/openclaw.json
CONFIG_DIR=/home/node/.openclaw
CONFIG="$CONFIG_DIR/openclaw.json"

mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG" ]; then
  cp "$TEMPLATE" "$CONFIG"
  echo "[entrypoint] seeded $CONFIG a partir do template versionado"
elif [ "${OPENCLAW_CONFIG_OVERWRITE:-false}" = "true" ]; then
  cp "$CONFIG" "$CONFIG.bak.$(date +%s)" 2>/dev/null || true
  cp "$TEMPLATE" "$CONFIG"
  echo "[entrypoint] OPENCLAW_CONFIG_OVERWRITE=true — re-seeded $CONFIG (backup .bak.* salvo)"
else
  echo "[entrypoint] $CONFIG ja existe — preservando edicoes manuais"
fi

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

exec "$@"
