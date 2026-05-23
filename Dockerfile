# syntax=docker/dockerfile:1.6
FROM node:24-bookworm

ARG OPENCLAW_REPO=https://github.com/openclaw/openclaw.git
ARG OPENCLAW_REF=main

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates curl socat zstd python3 python3-pip \
 && rm -rf /var/lib/apt/lists/*

# uv: instala Python 3.12 inline (bookworm so traz ate 3.11).
RUN curl -fsSL https://astral.sh/uv/install.sh | sh \
 && ln -sf /root/.local/bin/uv /usr/local/bin/uv \
 && ln -sf /root/.local/bin/uvx /usr/local/bin/uvx

# Meta Ads CLI oficial (pacote 'meta-ads' no PyPI, publicado por Meta em 2026-04-29).
# Instala em venv isolado gerenciado por uv; binario fica em /root/.local/bin/meta.
RUN uv tool install --python 3.12 meta-ads

# Python SDK do MCP para o middleware customizado (middleware/meta_ads_cli_mcp.py).
# Instalamos no mesmo Python 3.12 do uv via venv compartilhado.
RUN uv venv --python 3.12 /opt/middleware-venv \
 && /opt/middleware-venv/bin/pip install --no-cache-dir "mcp>=1.0"

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

# Middleware MCP que envelopa a CLI 'meta' como tools tipados para o openclaw.
COPY middleware /app/middleware

# Entrypoint: sobe `ollama serve` em background e exec o CMD (openclaw).
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV NODE_ENV=production
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["openclaw"]
