#!/bin/sh
# Inicia o ollama em background e em seguida executa o comando principal
# (por default `openclaw`, mas o compose sobrescreve com `openclaw gateway ...`).
set -e

ollama serve >/var/log/ollama.log 2>&1 &
OLLAMA_PID=$!

# Aguarda ollama responder em 127.0.0.1:11434 (timeout 30s)
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
