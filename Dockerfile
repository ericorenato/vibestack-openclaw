# syntax=docker/dockerfile:1.6
FROM node:24-bookworm

ARG OPENCLAW_REPO=https://github.com/openclaw/openclaw.git
ARG OPENCLAW_REF=main

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates curl socat \
 && rm -rf /var/lib/apt/lists/*

# ============================================================
# >>> BINÁRIOS CUSTOMIZADOS — adicione aqui suas dependências <<<
# Cada bloco deve baixar, extrair e dar chmod +x em /usr/local/bin/<nome>.
# Exemplos retirados do guia oficial (descomente/edite conforme precisar):
#
# RUN curl -L https://github.com/steipete/gogcli/releases/latest/download/gogcli_linux_amd64.tar.gz \
#       | tar -xzO gog > /usr/local/bin/gog \
#  && chmod +x /usr/local/bin/gog
#
# RUN curl -L https://github.com/steipete/goplaces/releases/latest/download/goplaces_linux_amd64.tar.gz \
#       | tar -xzO goplaces > /usr/local/bin/goplaces \
#  && chmod +x /usr/local/bin/goplaces
#
# RUN curl -L https://github.com/steipete/wacli/releases/latest/download/wacli-linux-amd64.tar.gz \
#       | tar -xzO wacli > /usr/local/bin/wacli \
#  && chmod +x /usr/local/bin/wacli
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

ENV NODE_ENV=production
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

CMD ["node","dist/index.js"]
