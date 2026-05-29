# vibestack-openclaw

Imagem Docker self-hosted do [OpenClaw](https://github.com/openclaw/openclaw) com Ollama embutido e middleware MCP customizado pra Meta Ads. Pronta pra subir numa VPS (Hetzner, DigitalOcean, AWS Lightsail — qualquer host com Docker) e acessar do laptop via SSH tunnel.

**O que você ganha rodando isso:**
- Um gateway OpenClaw acessível em `http://127.0.0.1:18789` (via tunnel do laptop).
- Ollama no mesmo container — modelos locais (`llama3.2:3b`, `qwen2.5:7b`, etc.) sem dependência de API paga.
- 70 tools MCP pra Meta Ads (campanhas, ad sets, ads, creatives, insights, catálogos, datasets/pixels, product sets/items/feeds, **custom audiences**, **lookalikes**, **duplicação de campanhas/adsets/ads**) — agente cria/edita/lê/duplica/segmenta direto. 60 via CLI oficial + 10 via Graph API direta (audience/copies, que a CLI não cobre).
- Bloco demarcado no `Dockerfile` pra "bakear" suas próprias CLIs/binários (gog, goplaces, wacli já vêm de exemplo).
- **Hermes Agent** (NousResearch) no mesmo container como alternativa ao OpenClaw — API OpenAI-compatible em `http://127.0.0.1:8642/v1`, com acesso às **mesmas** tools MCP (meta-ads, media-editor). Veja [Hermes Agent](#hermes-agent-alternativa-ao-openclaw).

---

## Sumário

- [Arquitetura em uma frase](#arquitetura-em-uma-frase)
- [Pré-requisitos](#pré-requisitos)
- [Instalação rápida (Linux / Mac / Windows)](#instalação-rápida-linux--mac--windows)
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
  - [Passo 13 — (Opcional) Habilitar subagentes](#passo-13--opcional-habilitar-subagentes)
  - [Passo 14 — (Opcional) Disparar cadeia de agentes via cron](#passo-14--opcional-disparar-cadeia-de-agentes-via-cron)
- [Atualizar o projeto na VPS](#atualizar-o-projeto-na-vps)
- [Baixar modelos no Ollama](#baixar-modelos-no-ollama)
- [Hermes Agent (alternativa ao OpenClaw)](#hermes-agent-alternativa-ao-openclaw)
- [Referência técnica](#referência-técnica)
- [Troubleshooting](#troubleshooting)

---

## Arquitetura em uma frase

Um container Docker (`openclaw-vibestack`) que roda **(a)** o gateway do OpenClaw na porta 18789 (loopback), **(b)** `ollama serve` em background na 11434, **(c)** um middleware Python MCP que envelopa a CLI oficial `meta-ads` da Meta como ~60 tools tipados pro agente, **(d)** o Claw3D Studio na 3000, e **(e)** o **Hermes Agent** na 8642 — uma alternativa ao OpenClaw que compartilha as mesmas tools MCP. Tudo em **portas separadas**, então coexistem sem conflito.

| Serviço            | Porta (loopback) | Processo                          |
|--------------------|------------------|-----------------------------------|
| OpenClaw gateway   | 18789            | `openclaw gateway` (principal)    |
| Ollama             | 11434            | `ollama serve`                    |
| Claw3D Studio      | 3000             | Next.js + socat                   |
| Hermes API server  | 8642             | `hermes gateway` (api_server)     |

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

## Instalação rápida (Linux / Mac / Windows)

Pra quem só quer subir: o `install.sh` faz tudo de forma idempotente — verifica o Docker, **pergunta os valores do `.env`** (quando ele ainda não existe), gera os segredos, cria os diretórios de dados no SO certo e builda a imagem. Ele **para antes** do `up` (você sobe a stack manualmente).

**Opção A — direto da web (clona sozinho):**

```bash
curl -fsSL https://raw.githubusercontent.com/ericorenato/vibestack-openclaw/main/install.sh | bash
docker compose up -d   # rode de dentro da pasta vibestack-openclaw criada pelo instalador
```

O instalador clona o repo em `./vibestack-openclaw` (mude com `OPENCLAW_DIR=/caminho`) e se re-executa de lá. Como ele faz perguntas, lê as respostas do terminal (`/dev/tty`) mesmo vindo de um `curl | bash`. Requer o repositório **público** (o `raw.githubusercontent.com` e o `git clone` anônimo dependem disso).

**Opção B — clonando você mesmo:**

```bash
git clone https://github.com/ericorenato/vibestack-openclaw.git
cd vibestack-openclaw
./install.sh          # no Windows: rode em Git Bash ou WSL
docker compose up -d  # iniciar a stack (manual)
```

> Modo não-interativo (CI / sem terminal): exporte `NONINTERACTIVE=1` e o `.env` é criado só com defaults + segredos gerados (preencha Meta Ads / B2 editando o arquivo depois).

O que o `install.sh` resolve automaticamente:

- **Docker**: no Linux instala via `get.docker.com`; no Mac/Windows detecta e aponta o download do Docker Desktop.
- **Volumes**: usa `~/.openclaw` e `~/.ollama` — funciona no Docker Desktop (Mac/Windows) sem mexer no File Sharing, e na VPS (`HOME=/root`) resolve pro mesmo `/root/.openclaw` de sempre. Isso elimina o erro `mounts denied: the path /root/.openclaw is not shared from the host`.
- **`.env`**: copia de `.env.example` se faltar e gera `OPENCLAW_GATEWAY_TOKEN`/`GOG_KEYRING_PASSWORD` (não sobrescreve valores já preenchidos). Você ainda precisa preencher o `META_ACCESS_TOKEN` e os `B2_*` se for usar Meta Ads / media-editor — veja [Passo 5](#passo-5--opcional-gerar-o-token-da-meta-ads) e [Passo 6](#passo-6--configurar-env).
- **CRLF**: normaliza o `entrypoint.sh` pra LF, evitando o erro `entrypoint not found` em checkouts feitos no Windows.

Depois do `up`, siga o [Passo 8](#passo-8--configurar-o-openclaw-uma-vez-por-vps) (configurar OpenClaw) em diante. Se preferir entender cada etapa na mão, o tutorial abaixo cobre tudo sem o instalador.

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

> Atalho: `./install.sh` já faz o `mkdir` dos diretórios de dados e o `docker compose build` (parando antes do `up`). Se rodou o instalador, pule direto pro `docker compose up -d`.

```bash
mkdir -p /root/.openclaw /root/.ollama   # dispensável se usou ./install.sh

docker compose build
docker compose up -d
docker compose logs -f openclaw-vibestack
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
docker compose exec openclaw-vibestack openclaw configure
```

Responde as perguntas (auth mode, modelo default, etc.). Detalhes em https://docs.openclaw.ai.

Depois do wizard, **reinicia o container** pra que o entrypoint registre o MCP:

```bash
docker compose up -d --force-recreate openclaw-vibestack
```

### Passo 9 — Confirmar MCP registrado

```bash
docker compose logs openclaw-vibestack | grep -iE "mcp|meta-ads"
```

Espera ver: `[entrypoint] mcp 'meta-ads' registrado`. Se aparecer `AVISO: ACCESS_TOKEN vazio`, volta no Passo 6 e preenche.

Pra inspecionar a config gravada:

```bash
docker compose exec openclaw-vibestack cat /root/.openclaw/openclaw.json | grep -A8 meta-ads
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
2. **MCP Servers** → você já deve ver `meta-ads` listado com ~70 tools. Se não aparecer, repete o Passo 9.
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
Pega os insights da última semana agrupados por campanha.
Lista minhas custom audiences.
Duplica o ad set <ID> com sufixo "-copy-test" em PAUSED.
```

> Duplicações nascem em `status="PAUSED"` por default — pode testar sem medo de gastar dinheiro.

Comandos diretos no container pra debug:

```bash
docker compose exec openclaw-vibestack meta auth status
docker compose exec openclaw-vibestack meta --output json ads campaign list
```

### Passo 13 — (Opcional) Habilitar subagentes

**Pule esse passo se você só vai operar com um agente único.** Esse passo libera o padrão de subagentes — um agente delega trabalho a outro via `sessions_spawn`, que é **bloqueante** e devolve o resultado como tool-result no mesmo turno do pai. É o que viabiliza fluxos como "atendimento delega análise pro analista, recebe os dados, sintetiza".

Por padrão o OpenClaw bloqueia spawn cruzado (`agentId is not allowed for sessions_spawn`). O comando abaixo destrava.

Todos os comandos rodam dentro do container:

```bash
docker compose exec -it openclaw-vibestack bash
```

**1. Habilita subagentes e allowlist de spawn cruzado**

```bash
openclaw config set agents.defaults.subagents.maxSpawnDepth 2
openclaw config set agents.defaults.subagents.allowAgents '["*"]'
openclaw config set agents.defaults.subagents.announceTimeoutMs 300000
```

O que cada chave faz:

- **`maxSpawnDepth: 2`** — permite orquestrador (atendimento spawna analista, que pode spawnar trabalhador). Deixe em `1` se não precisar de aninhamento.
- **`allowAgents: ["*"]`** — qualquer agente pode spawnar qualquer outro. É a chave que destrava `agentId is not allowed for sessions_spawn`.
- **`announceTimeoutMs: 300000`** — 5min de janela pra entrega do resultado do filho ao pai. Sobe se você espera tarefas longas.

**2. Cria os agentes adicionais em `agents.list`**

Cada agente é uma entrada em `agents.list` do `openclaw.json`. Exemplo mínimo do `analista`:

```json
{
  "id": "analista",
  "name": "Analista",
  "workspace": "/root/.openclaw/workspace/analista",
  "agentDir": "/root/.openclaw/agents/analista/agent"
}
```

Os agentes herdam tudo de `agents.defaults` — model, `workspace` base, e o bloco `subagents` que você setou no item 1. O catálogo de tools vem do `tools.profile` global (`"coding"` neste repo) — esse perfil já expõe as tools básicas + as tools de qualquer MCP registrado, então **você não precisa configurar `tools.alsoAllow` por agente** pra que o analista use `meta-ads__*`.

O `openclaw.json` deste repo traz um exemplo funcional com `atendimento` + `analista` nesse formato mínimo. Use como referência.

> `sessions_spawn` vem implícita do bloco `subagents` — o modelo a chama com `runtime: 'subagent'`, `agentId: '<destino>'`, `task: '<descrição>'`, e o turno do pai bloqueia até o filho retornar com o tool-result.
>
> `sessions_yield` **não existe** nesse build do OpenClaw (confirmado por grep no source). Não instrua o modelo a chamá-la — seria no-op e fecharia o turno antes do filho responder.

**3. Reinicia o gateway**

```bash
openclaw gateway restart
```

**4. Valida**

```bash
openclaw config get agents.defaults.subagents
openclaw config get agents.list
```

A primeira saída deve mostrar `maxSpawnDepth: 2`, `allowAgents: ["*"]`, `announceTimeoutMs: 300000`. A segunda deve listar `main` + seus agentes adicionais.

Depois disso, no chat do agente orquestrador (ex: `atendimento`), você pode pedir coisas como:

> Delegue ao analista listar minhas campanhas Meta Ads e me traga uma análise crítica.

E o orquestrador vai chamar `sessions_spawn(runtime: 'subagent', agentId: 'analista', task: '...')`, aguardar o tool-result no mesmo turno e sintetizar.

### Passo 14 — (Opcional) Disparar cadeia de agentes via cron

O OpenClaw inclui um scheduler interno (`openclaw cron`) que dispara mensagens pra agentes em horários ou intervalos. Combinado com o padrão de subagentes do Passo 13, dá pra orquestrar fluxos automáticos sem nenhum trigger externo — ex: atendimento delega análise pro analista, que consulta o MCP Meta Ads, e o atendimento sintetiza, tudo dentro de um único turno bloqueante.

**Exemplo funcional: atendimento → analista (com MCP Meta Ads)**

```bash
docker compose exec openclaw-vibestack openclaw cron add \
  --name "Cadeia atendimento→analista" \
  --at "30s" \
  --tz "America/Sao_Paulo" \
  --session isolated \
  --agent atendimento \
  --delete-after-run \
  --message "Você executa em UM ÚNICO turno bloqueante.

ETAPA 1 — Delegue ao Analista

Chame sessions_spawn com:
  runtime: 'subagent'
  agentId: 'analista'
  task: 'Use meta-ads para listar campanhas. Retorne tabela Markdown com colunas: ID, Nome, Status, Spend, Impressions, Clicks, Conversions.'

IMPORTANTE:
- sessions_spawn é BLOQUEANTE neste runtime
- Retorna o resultado do Analista como tool-result no mesmo turno
- NÃO chame sessions_yield (não existe nesta versão)
- Aguarde o tool-result antes de prosseguir

ETAPA 2 — Ainda no mesmo turno, processe o resultado

Sintetize:

## Resumo do que o Analista entregou
[2 linhas]

## Análise crítica
- Melhor campanha: [nome — motivo]
- Pior campanha: [nome — hipótese]
- Saturação detectada: [sim/não, onde]

## Recomendações (sem executar)
1. [ação]
2. [ação]
3. [ação]"
```

Pontos críticos do comando:

- **`--session isolated`** — obrigatório quando `--agent` aponta pra um agente que não é o `main`. O CLI rejeita `--session main` nesse caso com `sessionTarget "main" is only valid for the default agent`.
- **`--agent atendimento`** — quem recebe a mensagem. Esse é o orquestrador que vai spawnar o subagente.
- **`--delete-after-run`** — remove o job depois de uma execução. Use `--keep-after-run` se quiser deixar persistido (vira `idle` no `cron list` depois de rodar — comportamento esperado).
- **`sessions_spawn` é bloqueante** — não chame `sessions_yield` (não existe nesse build). O turno do pai aguarda o tool-result do spawn dentro do mesmo turno; tentar "ceder" o turno faz o pai morrer antes do filho anunciar e dispara `Subagent announce give up` nos logs.

**Listar e remover jobs:**

```bash
docker compose exec openclaw-vibestack openclaw cron list
docker compose exec openclaw-vibestack openclaw cron rm <jobId>
```

Jobs persistem em `/root/.openclaw/cron/jobs.json` — sobrevivem a `docker compose down`/restart por causa do volume do Passo 7.

---

## Atualizar o projeto na VPS

```bash
cd ~/vibestack-openclaw
git pull
docker compose build           # se Dockerfile ou middleware/ mudou
docker compose up -d --force-recreate openclaw-vibestack
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
docker compose exec openclaw-vibestack ollama pull llama3.2:3b
docker compose exec openclaw-vibestack ollama pull qwen2.5:7b
docker compose exec openclaw-vibestack ollama list
```

Modelos ficam em `/root/.ollama` no host (volume), persistem entre rebuilds.

Sugestões por tamanho:
- **3GB RAM**: `llama3.2:3b`, `phi3:mini`
- **8GB RAM**: `qwen2.5:7b`, `mistral:7b`
- **16GB+**: `qwen2.5:14b`, `llama3.1:8b-instruct`

---

## Hermes Agent (alternativa ao OpenClaw)

O [Hermes Agent](https://github.com/NousResearch/hermes-agent) da NousResearch vem
**baked no mesmo container** como uma alternativa ao OpenClaw. Ele é clonado do git no
build (pinado por `HERMES_REF`, igual OpenClaw/Claw3D), instalado num venv Python 3.11
com o extra `[all]` (browser/Playwright, mcp, messaging, etc.), e **compartilha as mesmas
tools MCP** que o OpenClaw — `meta-ads` e `media-editor` (mesmos scripts em
`/app/middleware`, mesmo venv).

Como roda numa **porta separada** (8642), coexiste com o OpenClaw (18789), Claw3D (3000)
e Ollama (11434) sem conflito — são processos independentes no mesmo container.

### O que o entrypoint faz no boot

1. **Registra as tools** fazendo um merge idempotente em `${HERMES_DATA_DIR}/config.yaml`
   sob a chave `mcp_servers` (preservando qualquer outra config que você editar). Sem
   filtro de `tools`, o Hermes habilita todas as tools de cada server.
2. **Sobe o `hermes gateway`** em background. A única plataforma que sobe sem token é o
   `api_server` (OpenAI-compatible), que **exige `HERMES_API_SERVER_KEY`** pra iniciar.

> O provider/modelo **não** é configurado pelo build (decisão de projeto). Igual ao
> OpenClaw, você configura depois — veja abaixo.

### Configurar o provider/modelo (uma vez)

```bash
# Wizard interativo de modelo/provider:
docker compose exec -it openclaw-vibestack hermes model

# ...ou edite direto o config.yaml (persiste no volume ${HERMES_DATA_DIR}):
#   ${HERMES_DATA_DIR}/config.yaml  -> chave model: { provider, default }
```

Providers suportados incluem OpenRouter, Anthropic, Nous Portal, Ollama local
(`http://127.0.0.1:11434`), e outros — escolha no wizard. Enquanto não houver provider,
o api_server sobe mas as completions falham.

### Acessar a API

A porta 8642 é publicada **apenas em loopback** na VPS. Do laptop:

```bash
ssh -N -L 8642:127.0.0.1:8642 root@YOUR_VPS_IP
```

```bash
# Health check (sem auth):
curl http://127.0.0.1:8642/health

# Listar modelos / chat (Bearer = HERMES_API_SERVER_KEY do .env):
curl http://127.0.0.1:8642/v1/models \
  -H "Authorization: Bearer $HERMES_API_SERVER_KEY"
```

Qualquer frontend OpenAI-compatible (Open WebUI, LobeChat, etc.) conecta apontando pra
`http://127.0.0.1:8642/v1` com a `HERMES_API_SERVER_KEY` como API key. O modelo exposto
chama-se `hermes-agent`.

### Confirmar as tools registradas

```bash
docker compose exec openclaw-vibestack hermes mcp list   # lista meta-ads e media-editor
docker compose logs openclaw-vibestack | grep hermes      # ver o boot do gateway
```

---

## Referência técnica

### Estrutura do repo

```
.
├── Dockerfile               # node:24 + openclaw + ollama + meta-ads CLI + middleware + claw3d + hermes
├── entrypoint.sh            # ollama serve + openclaw mcp set + claw3d + hermes gateway + exec CMD
├── docker-compose.yml       # serviço único openclaw-vibestack, env, volumes, portas
├── middleware/
│   ├── meta_ads_cli_mcp.py  # MCP server Python — 70 tools (CLI + Graph API)
│   └── requirements.txt
├── .env.example
└── README.md
```

### Tools do MCP Meta Ads

70 tools no total: 60 envelopando a CLI oficial `meta-ads` + 10 chamando direto a Graph API (Custom Audiences + duplicação de entidades — a CLI v1.0.1 não cobre nenhum dos dois).

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
- **Duplicação** (Graph API direta — endpoint `/copies`): `duplicate_campaign`, `duplicate_ad_set`, `duplicate_ad`. Default `status_option="PAUSED"` + `deep_copy=True`. Aceita `new_name` (renomeia depois de duplicar) ou `rename_suffix` (Meta acrescenta sufixo numa única chamada).

Todas as tools que envelopam a CLI aceitam `output_format` (`json` default | `table` | `plain` | `none`). Todos os `create_*` e `duplicate_*` partem com `status="paused"` / `status_option="PAUSED"` por segurança. As tools de audience hasham email/phone localmente em SHA256 antes de enviar (Meta exige PII hasheada) — use `already_hashed=True` se a lista já vier pronta.

### Convenções de segurança operacional do wrapper

- **Safe-by-default em writes**: todo `create_*` nasce em `paused`. Todo `duplicate_*` nasce em `PAUSED`. Pra ativar, o agente precisa chamar `resume_*` ou `update_*` explicitamente — não há atalho acidental pra produção.
- **Deletes obrigam `--force`**: não há prompt interativo no MCP, então o wrapper sempre passa `--force`. Quem chama `delete_*` está afirmando que tem certeza.
- **PII nunca trafega em claro**: `add_users_to_audience` / `remove_users_from_audience` aplicam SHA256 local. Mesmo se um log capturar a chamada de rede, não vaza email/phone original.
- **`act_` prefix normalizado**: `META_AD_ACCOUNT_ID` aceita com ou sem `act_`. O entrypoint adiciona se faltar — não dá pra quebrar a CLI por formato de ID.
- **Env explicitamente passado pro MCP child**: o `entrypoint.sh` declara `env` no `openclaw mcp set` em vez de confiar em propagação implícita. Sem isso a CLI da Meta retorna "No access token found" mesmo com env no container.
- **Saída JSON sanitizada**: `--no-color --no-input` em toda chamada da CLI evita ANSI sujando o `json.loads`. `"No results."` é normalizado pra `[]`. `current_ad_account` é sintetizado do env (a CLI não suporta JSON nesse subcomando).

### Arquitetura multi-agente recomendada (opcional)

Esse MCP é o **executor** — quem realmente fala com a Meta. Mas pra operar tráfego pago com qualidade, vale ter agentes especializados em torno dele. Padrão sugerido (6 agentes, todos no mesmo OpenClaw):

| Agente | Trigger | Lê | Escreve | MCP? |
|---|---|---|---|---|
| **Coletor** | Cron (ex: 6x/dia) | — | `snapshots/{ts}.json` | ✅ list/get/insights |
| **Analista** | Cron (ex: 3x/dia) | `snapshots/` | `insights/{ts}.json` | ❌ |
| **Estrategista** | Evento `insights-ready` | `insights/`, `snapshots/`, `decisions/` | `recommendations/{ts}.json` | ❌ |
| **Aprovador** | Evento `recommendations-ready` | `recommendations/` | `decisions/approved\|rejected/{ts}.json` | ❌ (usa Telegram) |
| **Executor** | Evento `action-approved` | `decisions/approved/` | `executions/{ts}.json` | ✅ pause/update/duplicate |
| **Auditor** | Cron semanal | tudo | `audit/{week}.json` | ❌ |

Princípios:
- **Coletor é read-only**. Nunca chama write tool.
- **Estrategista propõe, humano aprova, Executor executa**. Apenas o Executor toca em mutating tools, e só com `authorization_token` válido vindo do Aprovador.
- **Catálogo restrito de ações**: o Executor só roda `pause_*`, `update_*` (budget), `duplicate_*`. Tudo fora disso é alerta pra humano.
- **Memory > prompt**: snapshots e decisões ficam em memory shared, não em system prompt do agente — sobrevive a restart, dá pra auditar.

Esse padrão não está hardcoded no MCP — é arquitetura que você compõe na UI do OpenClaw. O MCP só expõe as ferramentas; cada agente decide quando usa.

> Pra esse padrão funcionar (Estrategista delegar pro Executor, Analista invocar o Coletor, etc.) você precisa habilitar subagentes — veja [Passo 13](#passo-13--opcional-habilitar-subagentes). Sem isso, o OpenClaw bloqueia spawn cruzado com `agentId is not allowed for sessions_spawn`. Pra agendar disparos automáticos sem trigger externo, combine com o [Passo 14](#passo-14--opcional-disparar-cadeia-de-agentes-via-cron).

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

- `${OPENCLAW_DATA_DIR}` (default `/root/.openclaw`) → `/root/.openclaw` no container (auth profiles, `openclaw.json`, workspace do agente — tudo num mount só).
- `${OLLAMA_DATA_DIR}` (default `/root/.ollama`) → `/var/lib/ollama` no container (modelos baixados).

### CLI `openclaw` dentro do container

A imagem inclui wrapper em `/usr/local/bin/openclaw` que aponta pra `node /app/dist/index.js`:

```bash
docker compose exec openclaw-vibestack openclaw security audit
docker compose exec openclaw-vibestack openclaw mcp list
docker compose exec openclaw-vibestack openclaw --help
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
docker compose logs openclaw-vibestack | grep -iE "mcp|access_token"
```

Procura `AVISO: falha ao registrar mcp 'meta-ads'`. Se aparecer, o `openclaw.json` não existe (precisa rodar o Passo 8) ou o schema rejeitou o JSON.

### `meta auth status` diz `Not authenticated`

ACCESS_TOKEN não chegou no container. Confirma no `.env` que `META_ACCESS_TOKEN` está preenchido (sem aspas extras, sem espaços) e re-up com `--force-recreate`.

### Agente diz "Permissions error" ao criar campanha

O System User não tem papel "Anunciante" (ou superior) na ad account, OU o token foi gerado sem o escopo `ads_management`. Volta no Passo 5 itens 4 e 6.

### `pnpm install` falha por lockfile

Mudança no upstream. Troca `OPENCLAW_REF` no `.env` pra uma tag/commit conhecidamente bom e rebuild.

### `agentId is not allowed for sessions_spawn`

Spawn cruzado entre agentes está desabilitado por padrão. Rode o [Passo 13](#passo-13--opcional-habilitar-subagentes) — especificamente o `agents.defaults.subagents.allowAgents '["*"]'` e o restart do gateway.

### Agente não vê tools de MCP (ex: `meta-ads__*`) no catálogo

As tools de MCP são herdadas pelo agente via o perfil global `tools.profile` (este repo usa `"coding"`, que já expõe as tools básicas + MCP). Se o agente não vê:

1. Confirme que `tools.profile` no `openclaw.json` está em `"coding"` ou `"full"` — perfis menores não expõem MCP.
2. Confirme que o MCP está registrado: `docker compose exec openclaw-vibestack openclaw mcp list` deve listar `meta-ads`. Se não, refaça o Passo 9.
3. Cheque os logs do gateway por linhas `tool policy removed N tool(s)` — algum override per-agente pode estar derrubando tools sem querer.

### `Subagent announce give up (retry-limit)` no log do cron

O agente pai encerrou o turno antes do subagente devolver o resultado. Causa típica: o prompt instrui o modelo a chamar `sessions_yield` (essa tool **não existe** nesse build do OpenClaw — confirmado por grep no source). O pattern correto é deixar `sessions_spawn` bloqueando o turno até o tool-result chegar; veja o exemplo no [Passo 14](#passo-14--opcional-disparar-cadeia-de-agentes-via-cron).

### `cron: sessionTarget "main" is only valid for the default agent`

`openclaw cron add --agent <outro>` exige `--session isolated`. Só o agente default (`main`) aceita `--session main`. Reescreve o comando com `--session isolated`.

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
