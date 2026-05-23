# vibestack-openclaw

Imagem Docker customizada do [OpenClaw](https://github.com/openclaw/openclaw) com bloco demarcado para "bake" de binários/CLIs adicionais, pronta para rodar em uma VPS Hetzner (ou qualquer host Docker).

Inclui também o **Ollama instalado dentro do mesmo container** (não em serviço separado) — o openclaw acha em `http://127.0.0.1:11434`, como se ambos estivessem rodando num mesmo desktop. Modelos persistem via volume.

O source do openclaw **não é versionado aqui** — o `Dockerfile` faz `git clone` do upstream em build-time, pinado pela variável `OPENCLAW_REF`.

---

## Estrutura

```
.
├── Dockerfile               # node:24-bookworm + openclaw + ollama + meta-ads + middleware
├── entrypoint.sh            # Seed do openclaw.json + ollama serve em background + exec CMD
├── docker-compose.yml       # Servico unico openclaw-gateway (porta 18789 + 11434 loopback)
├── config/
│   └── openclaw.json        # Template versionado da config do openclaw (IaC)
├── middleware/
│   ├── meta_ads_cli_mcp.py  # MCP server Python envelopando a CLI 'meta'
│   └── requirements.txt
├── .env.example
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

## 5) Meta Ads — CLI oficial + middleware MCP

A imagem inclui a [**Meta Ads CLI oficial**](https://developers.facebook.com/blog/post/2026/04/29/introducing-ads-cli/) (pacote [`meta-ads`](https://pypi.org/project/meta-ads/) no PyPI, publicado pela Meta) instalada via [`uv`](https://docs.astral.sh/uv/) com Python 3.12 isolado, mais um **middleware MCP customizado** em `middleware/meta_ads_cli_mcp.py` que expõe a CLI como tools tipados para o openclaw.

Por que CLI + middleware (e não o MCP oficial em `mcp.facebook.com/ads`)? O MCP oficial só aceita OAuth de clientes whitelisted (claude.ai, Claude Desktop, ChatGPT, Cursor) — agente self-hosted não passa. A CLI oficial aceita autenticação por env var (System User Token), e o middleware traduz cada subcomando da CLI em um tool MCP nomeado.

### Gerar o System User Token (uma vez só, no navegador)

Segue o [guia oficial Meta Ads CLI / Primeiros passos](https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-cli/setup/get-started):

1. **Criar um Meta Developer App** em https://developers.facebook.com/apps → Create App → tipo **Business** → adicionar produto **Marketing API**.
2. **Adicionar o App ao Business Manager** (Business Suite → Configurações → Contas → Apps → Adicionar).
3. **Criar System User** em Business Suite → Configurações → Usuários → **Usuários do Sistema** → Adicionar. Função: **Administrador**. Nome sugerido: "CLI de anúncios".
4. **Atribuir ativos** ao system user (botão Atribuir ativos). Inclua:
   - Contas de anúncios (com permissão **Gerenciar campanhas**)
   - Páginas comerciais (pra criativos)
   - Catálogos de produtos (se usar ads de catálogo)
   - Conjuntos de dados / Pixels (pra rastreio de conversão)
5. **Adicionar o system user como Admin do App** em Meta for Developers → seu App → **Configurações do App** → **Funções** → **Funções** → Adicionar Administradores → escolher o system user. **Sem esse passo o token sai sem permissão pra falar pelo App.**
6. **Gerar token**: Business Suite → Usuários do Sistema → seu user → **Gerar novo token** → escolher seu App → marcar os **7 escopos**:
   - `business_management`
   - `ads_management`
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_ads`
   - `catalog_management`
   - `read_insights`

   Adicione mais escopos se um tool específico do middleware exigir. **Copia o token agora** — System User Tokens **não expiram**.

### Configurar `.env`

```bash
cd ~/vibestack-openclaw
nano .env
# preencher:
# META_ACCESS_TOKEN=EAAxxxxx...
# META_AD_ACCOUNT_ID=act_123456789   # opcional — agente descobre via list_ad_accounts
```

O `docker-compose.yml` injeta esses dois como `ACCESS_TOKEN` e `AD_ACCOUNT_ID` (nomes que a CLI espera).

### Registro no openclaw.json (automático — Infrastructure as Code)

A entrada `mcpServers.meta-ads` já está no template versionado em [`config/openclaw.json`](config/openclaw.json). No primeiro boot do container, o `entrypoint.sh` copia esse template para `/home/node/.openclaw/openclaw.json` (= `/root/.openclaw/openclaw.json` no host via volume). **Nada a editar manualmente.**

Comportamento:
- **Arquivo não existe** → entrypoint seedará do template.
- **Arquivo já existe** → entrypoint **preserva** (sua edição manual ganha).
- **Quer forçar re-seed** → no `.env`: `OPENCLAW_CONFIG_OVERWRITE=true`, restart. Um backup `.bak.<timestamp>` do anterior fica salvo no mesmo diretório.

Para acrescentar outros MCP servers no futuro: edita `config/openclaw.json` no repo, commit, pull na VPS, e ou (a) deleta `/root/.openclaw/openclaw.json` antes do restart, ou (b) liga `OPENCLAW_CONFIG_OVERWRITE=true` no `.env`.

### Aplicar

```bash
docker compose build
docker compose up -d --force-recreate openclaw-gateway
docker compose logs -f openclaw-gateway | grep -iE "mcp|meta-ads|seeded"
```

Tools disponíveis para o agente: `list_ad_accounts`, `get_ad_account`, `current_ad_account`, `list_campaigns`, `get_campaign`, `create_campaign`, `delete_campaign`, `list_ad_sets`, `get_ad_set`, `list_ads`, `get_ad`, `list_creatives`, `get_creative`, `get_insights`, `list_catalogs`, `list_pages`.

### Testar isolado

```bash
# CLI responde?
docker compose exec openclaw-gateway meta --version
docker compose exec openclaw-gateway meta ads --help

# Status oficial da auth (checa token + scopes + app binding)
docker compose exec openclaw-gateway meta auth status

# Smoke test com o token
docker compose exec openclaw-gateway sh -c 'meta ads adaccount list --output json'

# Middleware (Ctrl+C pra sair — ele espera stdio)
docker compose exec openclaw-gateway /opt/middleware-venv/bin/python /app/middleware/meta_ads_cli_mcp.py
```

Se `meta auth status` reclamar:
- **"app not authorized" / "user not allowed"** → faltou o passo 5 (adicionar system user como Admin do App).
- **"insufficient scope"** ao chamar um tool específico → regenerar token marcando o escopo faltante.
- **"invalid token"** → token expirado ou copiado errado; regerar.

### Adicionar ou customizar tools

Edite `middleware/meta_ads_cli_mcp.py`, replicando o padrão:

```python
@mcp.tool()
def nome_do_tool(arg1: str, arg2: int = 10) -> Any:
    """Descrição que o agente vai ler para decidir quando chamar."""
    return _run("subcomando", "operacao", "--flag", arg1, "--n", str(arg2))
```

Commit + push + `docker compose build` + `docker compose up -d --force-recreate`.

---

## 6) CLI `openclaw` dentro do container

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

## 7) Persistência

Sobrevivem a `docker compose down`/rebuild:

- `${OPENCLAW_CONFIG_DIR}` → `/home/node/.openclaw` (config, auth profiles, `openclaw.json`)
- `${OPENCLAW_WORKSPACE_DIR}` → `/home/node/.openclaw/workspace`
- `${OLLAMA_DATA_DIR}` → `/var/lib/ollama` (modelos baixados pelo ollama)

---

## 8) Troubleshooting

- **Build falha com exit 137** → falta de RAM. Aumente swap ou suba para um VM maior.
- **`AllowTcpForwarding` bloqueado** → ajustar `sshd_config` conforme acima.
- **Porta em uso** → outro processo escutando em 18789; mudar `OPENCLAW_GATEWAY_PORT` no `.env`.
- **`pnpm install` falha por mudança no lockfile do upstream** → trocar `OPENCLAW_REF` para uma tag/commit conhecido.

---

## Referências

- Guia oficial Hetzner: https://docs.openclaw.ai/pt-BR/install/hetzner
- Bake de binários: https://docs.openclaw.ai/pt-BR/install/docker-vm-runtime#bake-required-binaries-into-the-image
- OpenClaw upstream: https://github.com/openclaw/openclaw
