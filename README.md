# vibestack-openclaw

Imagem Docker customizada do [OpenClaw](https://github.com/openclaw/openclaw) com bloco demarcado para "bake" de binários/CLIs adicionais, pronta para rodar em uma VPS Hetzner (ou qualquer host Docker).

O source do openclaw **não é versionado aqui** — o `Dockerfile` faz `git clone` do upstream em build-time, pinado pela variável `OPENCLAW_REF`.

---

## Estrutura

```
.
├── Dockerfile          # Base node:24-bookworm + clone do openclaw + bloco de binarios extras
├── docker-compose.yml  # Servico openclaw-gateway, bind em 127.0.0.1
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

mkdir -p /root/.openclaw/workspace
chown -R 1000:1000 /root/.openclaw

docker compose build
docker compose up -d openclaw-gateway
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

## 4) Persistência

Sobrevivem a `docker compose down`/rebuild:

- `${OPENCLAW_CONFIG_DIR}` → `/home/node/.openclaw` (config, auth profiles, `openclaw.json`)
- `${OPENCLAW_WORKSPACE_DIR}` → `/home/node/.openclaw/workspace`

---

## 5) Troubleshooting

- **Build falha com exit 137** → falta de RAM. Aumente swap ou suba para um VM maior.
- **`AllowTcpForwarding` bloqueado** → ajustar `sshd_config` conforme acima.
- **Porta em uso** → outro processo escutando em 18789; mudar `OPENCLAW_GATEWAY_PORT` no `.env`.
- **`pnpm install` falha por mudança no lockfile do upstream** → trocar `OPENCLAW_REF` para uma tag/commit conhecido.

---

## Referências

- Guia oficial Hetzner: https://docs.openclaw.ai/pt-BR/install/hetzner
- Bake de binários: https://docs.openclaw.ai/pt-BR/install/docker-vm-runtime#bake-required-binaries-into-the-image
- OpenClaw upstream: https://github.com/openclaw/openclaw
