# syntax=docker/dockerfile:1.6
FROM node:24-bookworm

ARG OPENCLAW_REPO=https://github.com/openclaw/openclaw.git
ARG OPENCLAW_REF=main
ENV HOME=/root

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates curl socat zstd python3 python3-pip ffmpeg ripgrep \
 && rm -rf /var/lib/apt/lists/*

# uv: instala Python 3.12 inline (bookworm so traz ate 3.11).
RUN curl -fsSL https://astral.sh/uv/install.sh | sh \
 && ln -sf /root/.local/bin/uv /usr/local/bin/uv \
 && ln -sf /root/.local/bin/uvx /usr/local/bin/uvx

# Meta Ads CLI oficial (pacote 'meta-ads' no PyPI, publicado por Meta em 2026-04-29).
# Instala em venv isolado gerenciado por uv; binario fica em /root/.local/bin/meta.
RUN uv tool install --python 3.12 meta-ads

# Python SDK do MCP para os middlewares customizados (meta_ads_cli_mcp.py, media_editor_mcp.py).
# Venv criado por uv vem sem pip — usamos `uv pip install` no venv ativo via VIRTUAL_ENV.
# boto3 e' usado pelo media_editor_mcp.py como cliente S3-compatible do Backblaze B2.
RUN uv venv --python 3.12 /opt/middleware-venv \
 && VIRTUAL_ENV=/opt/middleware-venv uv pip install --no-cache "mcp>=1.0" "boto3>=1.30"

ENV PATH=/root/.local/bin:$PATH

# Ollama — instalado dentro da imagem (mesmo padrao de um desktop linux).
# O script oficial baixa o binario, instala em /usr/local/bin/ollama e tenta
# criar servico systemd (passo ignorado em container, nao falha).
RUN curl -fsSL https://ollama.com/install.sh | sh

# Pasta persistente dos modelos — montada como volume pelo compose.
ENV OLLAMA_MODELS=/var/lib/ollama
RUN mkdir -p /var/lib/ollama

# ============================================================
# >>> BINÁRIOS CUSTOMIZADOS — adicione aqui suas dependências <<<
# Cada bloco baixa, extrai e dá chmod +x em /usr/local/bin/<nome>.
# Os repos do openclaw incluem a versão no nome do asset, então
# usamos ARG por binário — fácil de atualizar quando subir versão.
# ============================================================

ARG GOGCLI_VERSION=0.19.0
ARG GOPLACES_VERSION=0.4.3
ARG WACLI_VERSION=0.11.0

# gogcli (instala como `gog`)
RUN curl -fL "https://github.com/openclaw/gogcli/releases/download/v${GOGCLI_VERSION}/gogcli_${GOGCLI_VERSION}_linux_amd64.tar.gz" \
       | tar -xzO gog > /usr/local/bin/gog \
 && chmod +x /usr/local/bin/gog

# goplaces
RUN curl -fL "https://github.com/openclaw/goplaces/releases/download/v${GOPLACES_VERSION}/goplaces_${GOPLACES_VERSION}_linux_amd64.tar.gz" \
       | tar -xzO goplaces > /usr/local/bin/goplaces \
 && chmod +x /usr/local/bin/goplaces

# wacli
RUN curl -fL "https://github.com/openclaw/wacli/releases/download/v${WACLI_VERSION}/wacli_${WACLI_VERSION}_linux_amd64.tar.gz" \
       | tar -xzO wacli > /usr/local/bin/wacli \
 && chmod +x /usr/local/bin/wacli

# ============================================================

WORKDIR /app

# Clona o source do openclaw na versão escolhida (branch, tag ou commit leve)
RUN git clone --depth 1 --branch "${OPENCLAW_REF}" "${OPENCLAW_REPO}" /tmp/openclaw \
 && cp -a /tmp/openclaw/. /app/ \
 && rm -rf /tmp/openclaw

RUN corepack enable \
 && pnpm install --frozen-lockfile \
 && pnpm build \
 && pnpm ui:install \
 && pnpm ui:build

# Wrapper para usar `openclaw <comando>` em vez de `node dist/index.js <comando>`
RUN printf '#!/bin/sh\nexec node /app/dist/index.js "$@"\n' > /usr/local/bin/openclaw \
 && chmod +x /usr/local/bin/openclaw

# ============================================================
# Claw3D — visualizador 3D dos agentes OpenClaw (Next.js + Three.js).
# Roda como custom server (server/index.js) e proxia WebSocket pro
# gateway OpenClaw in-process. Sobe via entrypoint em background.
# ============================================================
ARG CLAW3D_REPO=https://github.com/iamlukethedev/Claw3D.git
ARG CLAW3D_REF=main

# Build-time gateway URL — embedded no bundle do browser via NEXT_PUBLIC_*.
# O server tem proxy em /api/gateway/ws, entao o browser usa same-origin;
# esse valor e' so o default que aparece nas configs do Studio.
ARG CLAW3D_BUILD_GATEWAY_URL=ws://localhost:18789

RUN git clone --depth 1 --branch "${CLAW3D_REF}" "${CLAW3D_REPO}" /opt/claw3d \
 && cd /opt/claw3d \
 # Patch: Claw3D hardcoda min/maxProtocol=3 no GatewayBrowserClient e
 # nodeGatewayClient. O OpenClaw main exige v4 desde 2026.5.12. Subimos
 # o range pra 4 — Claw3D ainda nao ofereceu update upstream entao adaptamos
 # aqui. Confere se os arquivos existem antes pra falhar barulhento em rebase.
 && grep -q 'minProtocol: 3' src/lib/gateway/openclaw/GatewayBrowserClient.ts \
 && grep -q 'minProtocol: 3' src/lib/gateway/nodeGatewayClient.ts \
 && sed -i 's/minProtocol: 3,/minProtocol: 4,/g; s/maxProtocol: 3,/maxProtocol: 4,/g' \
      src/lib/gateway/openclaw/GatewayBrowserClient.ts \
      src/lib/gateway/nodeGatewayClient.ts \
 && npm ci --no-audit --no-fund \
 && NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_GATEWAY_URL="${CLAW3D_BUILD_GATEWAY_URL}" \
    npm run build

# ============================================================
# Hermes Agent — alternativa ao OpenClaw (NousResearch).
# Mesmo padrao dos blocos acima: clone pinado + venv uv (Python 3.11) +
# extra [all] (browser, mcp, messaging, etc.). O entrypoint sobe o
# api_server OpenAI-compatible na 8642 e registra os MESMOS middlewares
# MCP (meta-ads, media-editor) que o OpenClaw usa.
#
# Codigo fica em /opt/hermes-agent (fora do volume); dados em
# /root/.hermes (HERMES_HOME, montado como volume pelo compose).
# ============================================================
ARG HERMES_REPO=https://github.com/NousResearch/hermes-agent.git
ARG HERMES_REF=main

RUN git clone --depth 1 --branch "${HERMES_REF}" "${HERMES_REPO}" /opt/hermes-agent

# venv 3.11 (Hermes exige >=3.11; uv baixa inline) + instala tudo ([all]).
RUN uv venv --python 3.11 /opt/hermes-agent/venv \
 && VIRTUAL_ENV=/opt/hermes-agent/venv uv pip install --no-cache -e '/opt/hermes-agent[all]'

# Playwright/Chromium (browser tool) — "instalar tudo". --with-deps puxa as
# libs de sistema do Chromium via apt (roda como root no build, sem prompt).
RUN cd /opt/hermes-agent && npx --yes playwright install --with-deps chromium

# Pre-build do dashboard web (Vite/React) que o `hermes dashboard` serve na 9119.
# Compila pra hermes_cli/web_dist (mesmo comando do erro de --skip-build do
# Hermes). Assim o entrypoint sobe a UI rapido; sem isso ele compilaria a cada
# boot. Se a UI nao precisar rebuild, o helper interno do Hermes pula sozinho.
RUN cd /opt/hermes-agent/web && npm install && npm run build

# Pre-build do TUI (ui-tui) que a aba "Chat" do dashboard spawna via `hermes --tui`.
# Sem isso, o 1o `hermes --tui` (inclusive o que a aba Chat dispara) faz npm
# install + build em runtime — o que derruba o WebSocket do chat por timeout/erro.
# Gera ui-tui/dist/entry.js; em runtime o Hermes detecta que ja' esta' buildado e pula.
RUN cd /opt/hermes-agent/ui-tui && npm install && npm run build

# Wrapper: limpa PYTHONPATH/PYTHONHOME (igual ao install.sh oficial, pra nao
# herdar o venv do middleware/uv) e exec o hermes do venv do Hermes.
RUN printf '#!/usr/bin/env bash\nunset PYTHONPATH PYTHONHOME\nexec /opt/hermes-agent/venv/bin/hermes "$@"\n' \
      > /usr/local/bin/hermes \
 && chmod +x /usr/local/bin/hermes

# Middleware MCP que envelopa a CLI 'meta' como tools tipados para o openclaw.
COPY middleware /app/middleware

# Entrypoint: sobe `ollama serve` em background e exec o CMD (openclaw).
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV NODE_ENV=production
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["openclaw"]
