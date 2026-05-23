# vibestack-openclaw

Imagem Docker customizada do [OpenClaw](https://github.com/openclaw/openclaw) com bloco demarcado para "bake" de binários/CLIs adicionais, pronta para rodar em uma VPS Hetzner (ou qualquer host Docker).

Inclui também o **Ollama instalado dentro do mesmo container** (não em serviço separado) — o openclaw acha em `http://127.0.0.1:11434`, como se ambos estivessem rodando num mesmo desktop. Modelos persistem via volume.

O source do openclaw **não é versionado aqui** — o `Dockerfile` faz `git clone` do upstream em build-time, pinado pela variável `OPENCLAW_REF`.

---

## Estrutura

```
.
├── Dockerfile          # node:24-bookworm + clone do openclaw + ollama + binarios extras + wrapper `openclaw`
├── entrypoint.sh       # Sobe `ollama serve` em background e exec o comando principal
├── docker-compose.yml  # Servico unico openclaw-gateway (porta 18789 + 11434 loopback)
├── .env.example        # Variaveis de ambiente — copiar para .env
├── .gitignore
└── README.md
```

---

## 1) Adicionar uma biblioteca/CLI nova à imagem

Edite o `Dockerfile`, localize o bloco demarcado:

```dockerfile
# ============================================================
# >>> BINÁRIOS CUSTOMIZADOS — adicione aqui suas dependências <<<
```

e insira um `RUN` no padrão:

```dockerfile
RUN curl -L <URL-do-tar.gz> | tar -xzO <nome-no-tar> > /usr/local/bin/<nome> \
 && chmod +x /usr/local/bin/<nome>
```

Para pacotes apt, adicione antes do bloco:

```dockerfile
RUN apt-get update \
 && apt-get install -y --no-install-recommends <pacotes> \
 && rm -rf /var/lib/apt/lists/*
```

Depois:

```bash
git add Dockerfile
git commit -m "Add <ferramenta> to image"
git push
```

E na VPS:

```bash
git pull
docker compose build
docker compose up -d
docker compose exec openclaw-gateway which <nome>
```

---

## 2) Setup inicial na VPS Hetzner

```bash
ssh root@YOUR_VPS_IP

apt-get update
apt-get install -y git curl ca-certificates
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version

git clone https://github.com/ericorenato/vibestack-openclaw.git
cd vibestack-openclaw

cp .env.example .env
# Preencher OPENCLAW_GATEWAY_TOKEN e GOG_KEYRING_PASSWORD:
#   openssl rand -hex 32
nano .env

mkdir -p /root/.openclaw/workspace /root/.ollama
chown -R 1000:1000 /root/.openclaw

docker compose build
docker compose up -d
docker compose logs -f openclaw-gateway
```

### Acesso via SSH tunnel (no laptop)

```bash
ssh -N -L 18789:127.0.0.1:18789 root@YOUR_VPS_IP
```

Abra `http://127.0.0.1:18789/` no navegador.

Se o tunnel não funcionar, verifique `/etc/ssh/sshd_config` na VPS:

```
AllowTcpForwarding local
```

e `systemctl restart ssh`.

---

## 3) Atualizar versão do openclaw

Edite no `.env`:

```env
OPENCLAW_REF=v1.2.3   # tag, branch ou commit
```

E rebuilde:

```bash
docker compose build --no-cache
docker compose up -d
```

---

## 4) Ollama (modelo local)

O ollama é **instalado dentro da mesma imagem** do openclaw (via `curl -fsSL https://ollama.com/install.sh | sh` no Dockerfile). O `entrypoint.sh` inicia `ollama serve` em background antes do openclaw, então quando o gateway sobe o ollama já está respondendo em `127.0.0.1:11434`.

Vantagem: openclaw acha o ollama como se ambos estivessem instalados num mesmo desktop — sem precisar trocar nenhuma URL no onboarding.

### Baixar um modelo

```bash
docker compose exec openclaw-gateway ollama pull llama3.2:3b
# ou qwen2.5:7b, mistral, phi3, etc.
docker compose exec openclaw-gateway ollama list
```

Modelos ficam em `${OLLAMA_DATA_DIR}` no host (default `/root/.ollama`), montados como volume em `/var/lib/ollama` no container. Persistem entre rebuilds.

### Configurar dentro do OpenClaw

Na UI/onboarding, o ollama aparece em `http://127.0.0.1:11434` (valor default do openclaw). Nada a alterar.

### Acessar a API do ollama do laptop (opcional)

A porta 11434 já é publicada em `127.0.0.1:11434` no host. Crie o tunnel:

```bash
ssh -N -L 11434:127.0.0.1:11434 root@YOUR_VPS_IP
curl http://127.0.0.1:11434/api/tags   # do laptop
```

---

## 5) CLI `openclaw` dentro do container

A imagem inclui um wrapper em `/usr/local/bin/openclaw` que aponta para `node /app/dist/index.js`. Então, em vez de:

```bash
docker compose exec openclaw-gateway node dist/index.js security audit
```

você roda:

```bash
docker compose exec openclaw-gateway openclaw security audit
docker compose exec openclaw-gateway openclaw --help
```

Funciona com qualquer subcomando do openclaw.

---

## 6) Persistência

Sobrevivem a `docker compose down`/rebuild:

- `${OPENCLAW_CONFIG_DIR}` → `/home/node/.openclaw` (config, auth profiles, `openclaw.json`)
- `${OPENCLAW_WORKSPACE_DIR}` → `/home/node/.openclaw/workspace`
- `${OLLAMA_DATA_DIR}` → `/var/lib/ollama` (modelos baixados pelo ollama)

---

## 7) Troubleshooting

- **Build falha com exit 137** → falta de RAM. Aumente swap ou suba para um VM maior.
- **`AllowTcpForwarding` bloqueado** → ajustar `sshd_config` conforme acima.
- **Porta em uso** → outro processo escutando em 18789; mudar `OPENCLAW_GATEWAY_PORT` no `.env`.
- **`pnpm install` falha por mudança no lockfile do upstream** → trocar `OPENCLAW_REF` para uma tag/commit conhecido.

---

## Referências

- Guia oficial Hetzner: https://docs.openclaw.ai/pt-BR/install/hetzner
- Bake de binários: https://docs.openclaw.ai/pt-BR/install/docker-vm-runtime#bake-required-binaries-into-the-image
- OpenClaw upstream: https://github.com/openclaw/openclaw
