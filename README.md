# vibestack-openclaw

Imagem Docker self-hosted do [OpenClaw](https://github.com/openclaw/openclaw) com Ollama embutido e middleware MCP customizado pra Meta Ads. Pronta pra subir numa VPS (Hetzner, DigitalOcean, AWS Lightsail — qualquer host com Docker) e acessar do laptop via SSH tunnel.

**O que você ganha rodando isso:**
- Um gateway OpenClaw acessível em `http://127.0.0.1:18789` (via tunnel do laptop).
- Ollama no mesmo container — modelos locais (`llama3.2:3b`, `qwen2.5:7b`, etc.) sem dependência de API paga.
- 60 tools MCP pra Meta Ads (campanhas, ad sets, ads, creatives, insights, catálogos, datasets/pixels, product sets/items/feeds) — agente cria/edita/lê campanhas direto.
- Bloco demarcado no `Dockerfile` pra "bakear" suas próprias CLIs/binários (gog, goplaces, wacli já vêm de exemplo).

---

## Sumário

- [Arquitetura em uma frase](#arquitetura-em-uma-frase)
- [Pré-requisitos](#pré-requisitos)
- [Tutorial completo do zero](#tutorial-completo-do-zero)
  - [Passo 1 — Provisionar a VPS](#passo-1--provisionar-a-vps)
  - [Passo 2 — SSH e setup inicial do servidor](#passo-2--ssh-e-setup-inicial-do-servidor)
  - [Passo 3 — Instalar Docker](#passo-3--instalar-docker)
  - [Passo 4 — Clonar o projeto](#passo-4--clonar-o-projeto)
  - [Passo 5 — (Opcional) Gerar o token da Meta Ads](#passo-5--opcional-gerar-o-token-da-meta-ads)
  - [Passo 6 — Configurar `.env`](#passo-6--configurar-env)
  - [Passo 7 — Build + Up](#passo-7--build--up)
  - [Passo 8 — Configurar o OpenClaw (uma vez por VPS)](#passo-8--configurar-o-openclaw-uma-vez-por-vps)
  - [Passo 9 — Confirmar MCP registrado](#passo-9--confirmar-mcp-registrado)
  - [Passo 10 — SSH tunnel do laptop](#passo-10--ssh-tunnel-do-laptop)
  - [Passo 11 — Abrir a UI e criar o primeiro agente](#passo-11--abrir-a-ui-e-criar-o-primeiro-agente)
  - [Passo 12 — Smoke test do MCP Meta Ads](#passo-12--smoke-test-do-mcp-meta-ads)
- [Atualizar o projeto na VPS](#atualizar-o-projeto-na-vps)
- [Baixar modelos no Ollama](#baixar-modelos-no-ollama)
- [Referência técnica](#referência-técnica)
- [Troubleshooting](#troubleshooting)

---

## Arquitetura em uma frase

Um container Docker (`openclaw-gateway`) que roda **(a)** o gateway do OpenClaw na porta 18789 (loopback), **(b)** `ollama serve` em background na 11434, e **(c)** um middleware Python MCP que envelopa a CLI oficial `meta-ads` da Meta como ~60 tools tipados pro agente.

O entrypoint registra o MCP automaticamente no boot via `openclaw mcp set`, propagando `ACCESS_TOKEN`/`AD_ACCOUNT_ID` pro processo filho.

---

## Pré-requisitos

- Uma VPS Linux (recomendado Ubuntu 22.04+ ou Debian 12+).
  - **RAM**: 4GB mínimo (2GB faz build do openclaw cair com OOM). 8GB+ confortável se for rodar Ollama com modelo grande.
  - **Disco**: 20GB+ (imagem ~3GB, modelos do Ollama 2–8GB cada).
- SSH key configurada no seu laptop pra acessar a VPS sem senha.
- (Opcional, pra Meta Ads) Conta no Meta Business Manager com permissão de admin.

> Esse tutorial assume Hetzner CX22 (CPX21 ainda melhor). Funciona em qualquer outro provider — só ajuste o IP no exemplo.

---

## Tutorial completo do zero

### Passo 1 — Provisionar a VPS

Cria uma VPS Ubuntu 22.04 no provider da sua escolha. Anote o IP público (vamos chamar de `YOUR_VPS_IP`).

Na Hetzner Cloud:
1. Console → **Add Server**.
2. Location: próxima de você (Nuremberg/Helsinki/Ashburn).
3. Image: **Ubuntu 22.04**.
4. Type: **CX22** (mínimo) ou **CPX21** (recomendado).
5. SSH Keys: marque sua chave pública (cria nova se não tiver).
6. **Create & Buy now**.

### Passo 2 — SSH e setup inicial do servidor

Do seu laptop:

```bash
ssh root@YOUR_VPS_IP
```

Dentro da VPS:

```bash
apt-get update && apt-get upgrade -y
apt-get install -y git curl ca-certificates nano
```

### Passo 3 — Instalar Docker

```bash
curl -fsSL https://get.docker.com | sh
docker --version
docker compose version
```

Espera ver versão do Docker e do compose plugin. Se `docker compose version` reclamar, instale o plugin:

```bash
apt-get install -y docker-compose-plugin
```

### Passo 4 — Clonar o projeto

```bash
cd ~
git clone https://github.com/ericorenato/vibestack-openclaw.git
cd vibestack-openclaw
```

> Substitua a URL pelo fork seu se for o caso.

### Passo 5 — (Opcional) Gerar o token da Meta Ads

**Pule esse passo se NÃO for usar o MCP da Meta Ads.** Vai poder usar o OpenClaw + Ollama normalmente, sem as 60 tools da Meta.

Siga o [guia oficial Meta Ads CLI / Primeiros passos](https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-cli/setup/get-started). Resumo:

1. **Criar Meta Developer App** em https://developers.facebook.com/apps → **Create App** → tipo **Business** → adicionar produto **Marketing API**.
2. **Adicionar o App ao seu Business Manager**: Business Suite → Configurações → Contas → Apps → **Adicionar**.
3. **Criar System User**: Business Suite → Configurações → Usuários → **Usuários do Sistema** → Adicionar. Função: **Administrador**. Nome sugerido: "vibestack-openclaw".
4. **Atribuir ativos** ao system user (botão **Atribuir ativos**):
   - Contas de anúncios — papel mínimo **Anunciante** (Admin recomendado pra criar/editar via MCP).
   - Páginas comerciais — pra criativos.
   - Catálogos — se for usar ads de catálogo/DPA.
   - Datasets/Pixels — pra tracking de conversão.
5. **Adicionar o system user como Admin do App**: Meta for Developers → seu App → Configurações → **Funções** → **Funções** → Adicionar Administradores → escolhe o system user.
   - **Sem esse passo, o token sai mas sem permissão pra falar pelo App.**
6. **Gerar token**: Business Suite → Usuários do Sistema → seu user → **Gerar novo token** → escolhe seu App → marca os 7 escopos:
   - `business_management`
   - `ads_management` ← libera write (criar campanha, ad set, ad)
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_ads`
   - `catalog_management`
   - `read_insights`

   **Copia o token agora.** System User Tokens não expiram.
7. **Anote o ID da ad account principal**: Ads Manager → menu superior → Configurações → ID é o número depois de `act_` na URL.

### Passo 6 — Configurar `.env`

```bash
cp .env.example .env
nano .env
```

Preencha **no mínimo**:

```env
# Gere com: openssl rand -hex 32
OPENCLAW_GATEWAY_TOKEN=<resultado-do-openssl>
GOG_KEYRING_PASSWORD=<outro-resultado-do-openssl>

# Só preenche se fez o Passo 5
META_ACCESS_TOKEN=EAA...
META_AD_ACCOUNT_ID=act_123456789   # ou só 123456789 — o entrypoint adiciona o 'act_' se faltar
```

Os outros valores no `.env.example` já têm defaults sensatos. Pra gerar segredos:

```bash
openssl rand -hex 32   # roda uma vez pro gateway token
openssl rand -hex 32   # roda outra pro keyring password
```

### Passo 7 — Build + Up

```bash
mkdir -p /root/.openclaw/workspace /root/.ollama
chown -R 1000:1000 /root/.openclaw

docker compose build
docker compose up -d
docker compose logs -f openclaw-gateway
```

O build leva ~5-10min na primeira vez (pnpm install do openclaw + uv install da meta-ads + ollama). Espera o log estabilizar — você deve ver:

```
[entrypoint] ollama pronto (pid=NN)
[entrypoint] mcp 'meta-ads' registrado
```

Sai do log com `Ctrl+C` (container continua rodando).

### Passo 8 — Configurar o OpenClaw (uma vez por VPS)

O OpenClaw exige um wizard inicial pra criar `openclaw.json`. **Esse passo é interativo**:

```bash
docker compose exec openclaw-gateway openclaw configure
```

Responde as perguntas (auth mode, modelo default, etc.). Detalhes em https://docs.openclaw.ai.

Depois do wizard, **reinicia o container** pra que o entrypoint registre o MCP:

```bash
docker compose up -d --force-recreate openclaw-gateway
```

### Passo 9 — Confirmar MCP registrado

```bash
docker compose logs openclaw-gateway | grep -iE "mcp|meta-ads"
```

Espera ver: `[entrypoint] mcp 'meta-ads' registrado`. Se aparecer `AVISO: ACCESS_TOKEN vazio`, volta no Passo 6 e preenche.

Pra inspecionar a config gravada:

```bash
docker compose exec openclaw-gateway cat /home/node/.openclaw/openclaw.json | grep -A8 meta-ads
```

Deve mostrar `command`, `args` e um objeto `env` com `ACCESS_TOKEN`, `AD_ACCOUNT_ID`, `BUSINESS_ID`.

### Passo 10 — SSH tunnel do laptop

A porta 18789 do gateway é publicada **apenas em loopback** (`127.0.0.1`) na VPS — não está exposta na internet. Você acessa via tunnel SSH do laptop:

```bash
# No laptop (não na VPS):
ssh -N -L 18789:127.0.0.1:18789 root@YOUR_VPS_IP
```

Deixa esse terminal aberto. Em outro terminal, opcionalmente também tunela o Ollama:

```bash
ssh -N -L 11434:127.0.0.1:11434 root@YOUR_VPS_IP
```

Se o tunnel não conectar, verifica no `/etc/ssh/sshd_config` da VPS:

```
AllowTcpForwarding yes
```

E `systemctl restart ssh` se mudou.

### Passo 11 — Abrir a UI e criar o primeiro agente

No browser do laptop:

```
http://127.0.0.1:18789
```

Cole o `OPENCLAW_GATEWAY_TOKEN` do `.env` quando pedir.

Na UI:
1. **Models** → confirma se aparece a opção Ollama (URL default `http://127.0.0.1:11434`). Se quiser usar API paga (Anthropic/OpenAI), adiciona aqui também.
2. **MCP Servers** → você já deve ver `meta-ads` listado com ~60 tools. Se não aparecer, repete o Passo 9.
3. **Agents** → **New Agent** → escolhe o model, marca o MCP `meta-ads` como disponível, dá nome ("AdsOps", por exemplo), e descreve o que ele faz no system prompt.

Exemplo de system prompt pro agente de Meta Ads:

```
Você é um operador de Meta Ads. Cria campanhas SEMPRE em PAUSED.
Antes de criar qualquer estrutura, lista o estado atual (list_campaigns,
list_ad_sets) e confirma com o usuário. Para insights, prefira janelas
last_7d a last_30d. Usa output_format='json' por default; se algum tool
voltar parse_error, retenta com output_format='plain'.
```

### Passo 12 — Smoke test do MCP Meta Ads

Conversa com o agente que você acabou de criar:

> Liste as campanhas da minha ad account principal.

Espera receber JSON com nome, ID, status, objetivo, budget. Se sim, está tudo no ar.

Outros testes úteis pra confiança:

```
Mostra a ad account ativa.
Pega os insights da última semana agrupados por dia.
```

Comandos diretos no container pra debug:

```bash
docker compose exec openclaw-gateway meta auth status
docker compose exec openclaw-gateway meta --output json ads campaign list
```

---

## Atualizar o projeto na VPS

```bash
cd ~/vibestack-openclaw
git pull
docker compose build           # se Dockerfile ou middleware/ mudou
docker compose up -d --force-recreate openclaw-gateway
```

Pra atualizar a versão do openclaw upstream, edita no `.env`:

```env
OPENCLAW_REF=v1.2.3   # tag, branch ou commit
```

E rebuild com `--no-cache`:

```bash
docker compose build --no-cache
docker compose up -d
```

---

## Baixar modelos no Ollama

```bash
docker compose exec openclaw-gateway ollama pull llama3.2:3b
docker compose exec openclaw-gateway ollama pull qwen2.5:7b
docker compose exec openclaw-gateway ollama list
```

Modelos ficam em `/root/.ollama` no host (volume), persistem entre rebuilds.

Sugestões por tamanho:
- **3GB RAM**: `llama3.2:3b`, `phi3:mini`
- **8GB RAM**: `qwen2.5:7b`, `mistral:7b`
- **16GB+**: `qwen2.5:14b`, `llama3.1:8b-instruct`

---

## Referência técnica

### Estrutura do repo

```
.
├── Dockerfile               # node:24 + openclaw + ollama + meta-ads CLI + middleware
├── entrypoint.sh            # ollama serve + openclaw mcp set + exec CMD
├── docker-compose.yml       # serviço único openclaw-gateway, env, volumes, portas
├── middleware/
│   ├── meta_ads_cli_mcp.py  # MCP server Python — 60 tools envelopando 'meta ads'
│   └── requirements.txt
├── .env.example
└── README.md
```

### Tools do MCP Meta Ads

67 tools no total: 60 envelopando a CLI oficial `meta-ads` + 7 chamando direto a Graph API pra Custom Audiences (a CLI v1.0.1 não cobre audiences).

- **Ad Accounts**: `list_ad_accounts`, `get_ad_account`, `current_ad_account`
- **Campaigns**: `list_campaigns`, `get_campaign`, `create_campaign`, `update_campaign`, `pause_campaign`, `resume_campaign`, `archive_campaign`, `delete_campaign`
- **Ad Sets**: `list_ad_sets`, `get_ad_set`, `create_ad_set`, `update_ad_set`, `pause_ad_set`, `resume_ad_set`, `delete_ad_set`
- **Ads**: `list_ads`, `get_ad`, `create_ad`, `update_ad`, `pause_ad`, `resume_ad`, `delete_ad`
- **Creatives**: `list_creatives`, `get_creative`, `create_creative`, `create_creative_dco`, `update_creative`, `delete_creative`
- **Insights**: `get_insights` (date_preset, since/until, breakdown, fields, filtros)
- **Catalogs**: `list_catalogs`, `get_catalog`, `create_catalog`, `update_catalog`, `delete_catalog`
- **Pages**: `list_pages`, `get_page`
- **Datasets/Pixels**: `list_datasets`, `get_dataset`, `create_dataset`, `connect_dataset`, `disconnect_dataset`, `assign_user_to_dataset`
- **Product Sets**: `list_product_sets`, `get_product_set`, `create_product_set`, `update_product_set`, `delete_product_set`
- **Product Items**: `list_product_items`, `get_product_item`, `create_product_item`, `update_product_item`, `delete_product_item`
- **Product Feeds**: `list_product_feeds`, `get_product_feed`, `create_product_feed`, `update_product_feed`, `delete_product_feed`
- **Custom Audiences** (Graph API direta, não passa pela CLI): `list_custom_audiences`, `get_custom_audience`, `create_custom_audience`, `create_lookalike_audience`, `add_users_to_audience`, `remove_users_from_audience`, `delete_custom_audience`

Todas as tools que envelopam a CLI aceitam `output_format` (`json` default | `table` | `plain` | `none`). Todos os `create_*` partem com `status="paused"` por segurança. As tools de audience hasham email/phone localmente em SHA256 antes de enviar (Meta exige PII hasheada) — use `already_hashed=True` se a lista já vier pronta.

### Adicionar uma CLI nova à imagem

Edita o `Dockerfile`, localiza o bloco demarcado `BINÁRIOS CUSTOMIZADOS`, e adiciona:

```dockerfile
ARG MEUBIN_VERSION=1.0.0
RUN curl -fL "https://github.com/org/meubin/releases/download/v${MEUBIN_VERSION}/meubin_linux_amd64.tar.gz" \
       | tar -xzO meubin > /usr/local/bin/meubin \
 && chmod +x /usr/local/bin/meubin
```

Commit + push + na VPS: `git pull && docker compose build && docker compose up -d --force-recreate`.

### Adicionar um MCP server novo

1. Cria o servidor (Python/Node/Go — qualquer linguagem que fale o protocolo MCP) em `middleware/seu_mcp.py`.
2. Edita `entrypoint.sh`, no bloco "Registro de MCP servers", adiciona:

   ```sh
   register_mcp seu-server '{"command":"/caminho/binario","args":["arg1"],"env":{"VAR":"val"}}'
   ```

3. Commit, pull na VPS, `docker compose up -d --force-recreate`.

### Persistência

Sobrevivem a `docker compose down`/rebuild:

- `${OPENCLAW_CONFIG_DIR}` (default `/root/.openclaw`) → `/home/node/.openclaw` no container (auth profiles, `openclaw.json`).
- `${OPENCLAW_WORKSPACE_DIR}` (default `/root/.openclaw/workspace`) → workspace do agente.
- `${OLLAMA_DATA_DIR}` (default `/root/.ollama`) → `/var/lib/ollama` no container (modelos baixados).

### CLI `openclaw` dentro do container

A imagem inclui wrapper em `/usr/local/bin/openclaw` que aponta pra `node /app/dist/index.js`:

```bash
docker compose exec openclaw-gateway openclaw security audit
docker compose exec openclaw-gateway openclaw mcp list
docker compose exec openclaw-gateway openclaw --help
```

---

## Troubleshooting

### Build cai com `exit 137`

Falta de RAM. Aumenta swap (`fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`) ou sobe pra VPS com mais memória.

### `AllowTcpForwarding` bloqueado

```bash
sed -i 's/^#*AllowTcpForwarding.*/AllowTcpForwarding yes/' /etc/ssh/sshd_config
systemctl restart ssh
```

### Porta 18789 em uso na VPS

Outro processo escutando. Muda `OPENCLAW_GATEWAY_PORT` no `.env` e re-up.

### MCP `meta-ads` não aparece na UI

```bash
docker compose logs openclaw-gateway | grep -iE "mcp|access_token"
```

Procura `AVISO: falha ao registrar mcp 'meta-ads'`. Se aparecer, o `openclaw.json` não existe (precisa rodar o Passo 8) ou o schema rejeitou o JSON.

### `meta auth status` diz `Not authenticated`

ACCESS_TOKEN não chegou no container. Confirma no `.env` que `META_ACCESS_TOKEN` está preenchido (sem aspas extras, sem espaços) e re-up com `--force-recreate`.

### Agente diz "Permissions error" ao criar campanha

O System User não tem papel "Anunciante" (ou superior) na ad account, OU o token foi gerado sem o escopo `ads_management`. Volta no Passo 5 itens 4 e 6.

### `pnpm install` falha por lockfile

Mudança no upstream. Troca `OPENCLAW_REF` no `.env` pra uma tag/commit conhecidamente bom e rebuild.

### JSON malformado em algum tool

Já tem proteção: `--no-color --no-input` + normalização de `"No results."` → `[]` + `current_ad_account` sintético do env. Se ainda aparecer, o agente pode chamar a tool com `output_format="plain"` e a CLI manda texto cru (o agente parseia).

---

## Referências

- OpenClaw: https://github.com/openclaw/openclaw
- Docs OpenClaw: https://docs.openclaw.ai
- Meta Ads CLI (PyPI): https://pypi.org/project/meta-ads/
- Meta Ads CLI guia oficial: https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-cli
- Ollama: https://ollama.com
- MCP (Model Context Protocol): https://modelcontextprotocol.io
