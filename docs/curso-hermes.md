# Curso prático: Hermes Agent (e como ele se compara ao OpenClaw)

> **Para quem é este material:** donos de negócio e gestores **sem experiência prévia em IA**. Você já configurou o OpenClaw nas aulas anteriores; aqui vamos nos aprofundar no **Hermes**, o "irmão" dele que roda no mesmo servidor. Tudo explicado em linguagem simples, com analogias, passo a passo e comandos prontos para copiar.

> **Onde rodar os comandos:** neste projeto o Hermes vive **dentro do container** `openclaw-vibestack`. Então, na prática, todo comando `hermes ...` deste guia você roda assim:
> ```bash
> docker compose exec -it openclaw-vibestack hermes <comando>
> ```
> Para encurtar, o guia escreve só `hermes <comando>` — lembre de prefixar com `docker compose exec -it openclaw-vibestack`.

---

## Sumário

1. [IA em 5 minutos (os 4 conceitos que bastam)](#1-ia-em-5-minutos)
2. [O que é o Hermes](#2-o-que-é-o-hermes)
3. [Hermes × OpenClaw: semelhanças e diferenças](#3-hermes--openclaw-semelhanças-e-diferenças)
4. [Primeiro contato: acessar e configurar o Hermes](#4-primeiro-contato)
5. [Os comandos da CLI do Hermes (mapa por categoria)](#5-os-comandos-da-cli)
6. [Como "criar agentes" no Hermes](#6-como-criar-agentes-no-hermes)
7. [O "organograma": como montar um time no Hermes](#7-o-organograma-como-montar-um-time)
8. [Transferir seus agentes do OpenClaw para o Hermes](#8-transferir-do-openclaw-para-o-hermes)
9. [Crons e "heartbeats": colocar o agente para trabalhar sozinho](#9-crons-e-heartbeats)
10. [O diferencial do Hermes: memória e skills](#10-memória-e-skills)
11. [Glossário e checklist](#11-glossário-e-checklist)

---

## 1. IA em 5 minutos

Antes de tudo, quatro palavras que vão aparecer o tempo todo. Pense numa **empresa**:

| Termo | O que é (analogia de empresa) |
|---|---|
| **Modelo (LLM)** | O "cérebro" que pensa e escreve. Ex.: GPT, Claude, Llama. É como contratar um **funcionário inteligente** — uns são mais caros e espertos, outros mais baratos. |
| **Provider (provedor)** | A "empresa de RH" de onde vem esse cérebro: OpenAI, Anthropic, OpenRouter, Ollama (modelos locais, de graça). Você escolhe de quem "aluga" o cérebro. |
| **Agente** | O funcionário **com instruções, memória e ferramentas**. Não é só o cérebro — é o cérebro + um manual de função + acesso a sistemas. |
| **MCP (ferramentas)** | As "chaves de acesso aos sistemas da empresa". Um MCP dá ao agente a capacidade de **fazer coisas** no mundo real: criar campanha no Meta Ads, editar um vídeo, mandar WhatsApp. Sem MCP, o agente só conversa; com MCP, ele **executa**. |

Guarde a ideia central: **um agente = cérebro (modelo) + instruções + memória + ferramentas (MCP)**. OpenClaw e Hermes são duas formas diferentes de montar e operar esse agente.

---

## 2. O que é o Hermes

O **Hermes Agent** (feito pela Nous Research) se descreve como *"o agente que cresce com você"*. A grande sacada dele é um **ciclo de autoaprendizado**: ele

- **cria "skills" (habilidades) a partir da experiência** — aprende um procedimento uma vez e guarda para reusar;
- **lembra de você entre conversas** — monta um perfil seu (preferências, contexto) e consulta conversas passadas;
- **roda em qualquer lugar** — de um servidor de R$ 25/mês a um cluster de GPUs;
- **fala por vários canais** — Telegram, Discord, Slack, WhatsApp, e-mail e ~20 outros, tudo por um único "gateway".

E ele é **compatível com OpenAI nos dois sentidos**:
- **consome** qualquer modelo (você pluga OpenAI, Anthropic, OpenRouter, Ollama… sem trocar código);
- **se expõe** como uma API igual à da OpenAI — então qualquer app de chat (Open WebUI, LobeChat) se conecta a ele.

> **Resumo de uma linha:** o Hermes é um **agente generalista que aprende sozinho**, acessível por chat, por vários mensageiros e por API — e você pode rodar **vários deles** (cada um é um *profile*; veja a Seção 6).

---

## 3. Hermes × OpenClaw: semelhanças e diferenças

Os dois fazem a mesma coisa de base: são **agentes de IA self-hosted** (rodam no *seu* servidor), usam **MCP** para executar ações e aceitam **vários provedores de modelo**. Neste projeto, inclusive, **compartilham os mesmos MCP servers** (`meta-ads`, `media-editor`, `whatsapp`, `higgsfield`, `atlascloud`). A diferença está na **filosofia de organização**.

### A diferença que mais importa: **como os agentes se coordenam**

Os **dois têm vários agentes**. A diferença não é "um × muitos" — é **como eles trabalham juntos**.

- **OpenClaw = organograma com repasse automático.** Você cria **agentes nomeados e permanentes** (Diretor, Analista, Gestor…) que **se chamam sozinhos dentro de uma mesma conversa** (o Diretor aciona o Analista, que aciona o Gestor, num único turno). É a sua pasta `agency/`. Pense numa **agência com departamentos que conversam em tempo real**.
- **Hermes = vários agentes (chamados *profiles*) que colaboram por um "quadro de trabalho".** Cada **profile** é um agente completo e independente (personalidade, modelo, memória e ferramentas próprios). Eles **não se chamam automaticamente** dentro de uma conversa; em vez disso, coordenam-se por **mecanismos compartilhados**: o **quadro Kanban** (você atribui uma tarefa a um profile e ele a executa), o **swarm** (vários profiles em paralelo → verificador → sintetizador) e a **delegação efêmera** (ajudantes temporários para subtarefas). Pense num **time que se organiza por um quadro de tarefas**, não por uma ligação ao vivo entre departamentos.

> ⚠️ **Correção importante (e a resposta às suas perguntas):** o Hermes **é multi-agente sim** — só que "agente" no Hermes se chama **profile**. Por isso a interface tem área de multi-agente e por isso a importação do OpenClaw traz **vários** (um profile por agente). O que o Hermes **não** faz é o **repasse automático nomeado dentro de um único turno** (o "organograma vivo" do OpenClaw). Veja a [Seção 7](#7-o-organograma-como-montar-um-time) e o [FAQ](#faq-multi-agente-profiles-e-organograma).

### Tabela comparativa

| Tema | OpenClaw | Hermes |
|---|---|---|
| **Vários agentes?** | Sim — **agentes nomeados** na `agency/` | **Sim** — cada agente é um **profile** |
| **Como se coordenam** | **Repasse automático** entre agentes dentro de um turno (organograma vivo) | Por **quadro Kanban** (tarefa → profile), **swarm** e **delegação efêmera** — sem repasse automático nomeado |
| **Dividir uma tarefa na hora** | Subagentes nomeados e persistentes (Diretor → Analista → Gestor) | **Delegação efêmera** (`delegate_task`): ajudantes temporários, sem memória, que retornam só um resumo |
| **Memória / aprendizado** | Memória por agente (você configura) | **Ciclo de autoaprendizado nativo**: cria *skills*, monta perfil do usuário, busca conversas antigas |
| **Definição do agente** | Arquivos por agente: `IDENTITY/SOUL/USER/TOOLS/AGENTS.md` | Um **profile** = `SOUL.md` (personalidade) + `config.yaml` próprios |
| **Agendamento (cron)** | Tem `openclaw cron` | Tem `hermes cron` (built-in, "tica" a cada 60s) |
| **Ferramentas (MCP)** | Sim | Sim (mesmos servers) |
| **API estilo OpenAI** | — (acesso pela UI/gateway) | **Sim** (`/v1/chat/completions`) — conecta em apps de chat |
| **Canais de mensagem** | WhatsApp (via bridge deste projeto) | **Gateway nativo**: Telegram, Discord, Slack, WhatsApp, e-mail… |
| **Interfaces** | UI web (porta 18789) | TUI no terminal + **dashboard web** (porta 9119) + API (porta 8642) |

### Quando usar cada um

- **Use o OpenClaw** quando você quer um **organograma com repasse automático** entre papéis dentro de uma conversa (Diretor aciona Analista aciona Gestor no mesmo turno) — é o seu caso da agência de tráfego.
- **Use o Hermes** quando você quer **agentes que aprendem com o uso**, acessíveis por vários mensageiros e por API, coordenados por um **quadro de tarefas** (Kanban) em vez de repasse automático — ótimo para fila de trabalho e automação.

> **Boa notícia:** neste projeto os dois rodam **lado a lado, no mesmo container**, em portas diferentes. Você não precisa escolher — pode usar os dois.

---

## 4. Primeiro contato

Neste projeto, o Hermes **já sobe junto com o container** (o `entrypoint.sh` inicia o `hermes gateway` na porta **8642** e o `hermes dashboard` na **9119**). Os dados dele ficam em `/root/.hermes` (volume persistente — sobrevive a reinício).

### 4.1 Acessar o dashboard (a "página de gestão")

No Mac/Windows, direto no navegador: **http://127.0.0.1:9119**
Na VPS, via túnel SSH (do seu laptop):
```bash
ssh -N -L 9119:127.0.0.1:9119 root@SEU_VPS_IP
```
Depois abra `http://127.0.0.1:9119`. O dashboard tem abas de **Status, Chat, Configuração, Sessões, Logs, Cron, Skills, MCP** e mais.

### 4.2 Configurar o cérebro (modelo/provedor) — passo obrigatório

O build **não** escolhe o modelo por você (de propósito). Rode uma vez o assistente interativo:
```bash
hermes model
```
Ele pergunta o **provedor** (ex.: OpenRouter, Anthropic, OpenAI, Ollama para modelos locais, ou o Nous Portal) → faz login/pede a chave → você escolhe o **modelo**. Pronto, o cérebro está plugado.

### 4.3 Conversar pela primeira vez

No terminal (modo conversa):
```bash
hermes
```
Ou uma pergunta única (entra, responde, sai):
```bash
hermes -q "Liste minhas campanhas ativas no Meta Ads"
```

### 4.4 Conectar um app de chat (opcional)

O Hermes expõe uma API igual à da OpenAI em `http://127.0.0.1:8642/v1`. Em apps como Open WebUI/LobeChat, aponte para essa URL e use como "API Key" o valor do `HERMES_API_SERVER_KEY` do seu `.env`. Teste rápido:
```bash
curl http://127.0.0.1:8642/v1/models -H "Authorization: Bearer SEU_HERMES_API_SERVER_KEY"
```

---

## 5. Os comandos da CLI

A CLI do Hermes é grande. Não decore tudo — entenda por **categoria**. Estão marcados com ⭐ os que você mais vai usar.

**Conversar**
- ⭐ `hermes` / `hermes chat` — abre a conversa (TUI). `hermes --tui` força a interface rica.
- `hermes -q "..."` — pergunta única (one-shot). `hermes -z "..."` — versão "crua" (só entra prompt, sai a resposta).

**Configurar / contas**
- ⭐ `hermes model` — escolher provedor + modelo.
- `hermes setup` — assistente de configuração (modelo, terminal, gateway, ferramentas…). `hermes setup --quick` para o caminho rápido.
- ⭐ `hermes config show | edit | set <chave> <valor> | path | check` — ver/editar a configuração.
- `hermes auth add|list|remove|status` — gerenciar chaves de provedores.

**Gateway / mensageiros**
- ⭐ `hermes gateway run|start|stop|restart|status` — liga o "carteiro" que conecta WhatsApp/Telegram/etc. **e** sobe a API (porta 8642). *(Neste projeto, o entrypoint já roda isso por você.)*
- `hermes send -t <destino> "msg"` — manda mensagem por um canal.
- `hermes whatsapp` — parear WhatsApp (QR). `hermes pairing list|approve|revoke` — aprovar quem pode falar com o agente.

**Ferramentas (MCP)**
- ⭐ `hermes mcp list` — ver os MCP conectados (deve mostrar `meta-ads`, `media-editor`, `whatsapp`, `higgsfield`, `atlascloud`).
- `hermes mcp add <nome> --command ... | --url ...` — adicionar um MCP. `hermes mcp test|configure|catalog|install`.

**Aprendizado (o diferencial)**
- `hermes skills browse|search|install|list` — habilidades (Seção 10).
- `hermes memory setup|status|off` — memória de longo prazo (Seção 10).
- `hermes sessions list|browse|export|search` — histórico de conversas (busca full-text).

**Automação**
- ⭐ `hermes cron list|create|edit|pause|resume|run|remove|status` — agendamento (Seção 9).
- `hermes kanban` — um quadro de tarefas (mais sobre isso na Seção 7).

**Migração e manutenção**
- ⭐ `hermes claw migrate` — **importa do OpenClaw** (Seção 8).
- `hermes profile list|create|use|...` — múltiplas "instâncias" isoladas (Seção 6/7).
- `hermes status | logs | doctor --fix | dashboard | version | update` — diagnóstico e UI.

> Para ver as opções de qualquer comando: `hermes <comando> --help` (ex.: `hermes cron --help`).

---

## 6. Como "criar agentes" no Hermes

**No Hermes, cada agente é um *profile*.** Um profile é um agente completo e independente, com:
- **`SOUL.md`** (personalidade: tom de voz, princípios, o que faz e não faz — equivale a `IDENTITY.md` + `SOUL.md` do OpenClaw juntos);
- **`config.yaml`** (configurações: modelo, autonomia, memória, MCP);
- **memória, sessões e skills próprios**.

O profile **`default`** já existe. Para ter mais agentes, você cria mais profiles.

### Profile (Hermes) × Agente (OpenClaw): a tradução

| No OpenClaw | No Hermes | Observação |
|---|---|---|
| Um **agente** da `agency/` (ex.: Analista) | Um **profile** (ex.: `analista`) | 1 agente OpenClaw = 1 profile Hermes |
| `IDENTITY.md` + `SOUL.md` do agente | **`SOUL.md`** do profile | Junte os dois num arquivo |
| `USER.md` (com quem fala/tom) | Trechos do `SOUL.md` + perfil de usuário (`memories/USER.md`) | — |
| `AGENTS.md` (fluxo, alçada, "não faça") | Regras no `SOUL.md` + uma **skill** com o procedimento | — |
| `TOOLS.md` (quais MCP) | `config.yaml` → `mcp_servers` | O profile vê as ferramentas conectadas |
| Agentes **se chamam automaticamente** | Profiles colaboram pelo **Kanban/swarm/delegação** | Diferença central (veja [FAQ](#faq-multi-agente-profiles-e-organograma)) |

> Em uma frase: **"criar um agente no Hermes" = "criar um profile".**

### ⚠️ Onde se faz isso (NÃO é na interface)

A maior parte do "cadastro" de um agente **não é feita pela UI**. A interface serve para **operar e ajustar configs**; **criar um profile** e **escrever o `SOUL.md`** são feitos por **CLI + arquivos**. E como `~/.hermes` é um **volume montado**, esses arquivos ficam **direto no seu computador** — você abre no VS Code/Finder.

```
~/.hermes/                         ← profile DEFAULT
├── SOUL.md                        ← personalidade do agente default   ← EDITE AQUI
├── config.yaml                    ← configurações do default          ← EDITE AQUI
├── memories/  skills/  cron/  sessions/ ...
└── profiles/
    └── analista/                  ← cada profile = um agente à parte
        ├── SOUL.md                ← personalidade do analista         ← EDITE AQUI
        └── config.yaml            ← configurações do analista         ← EDITE AQUI
```

| O que você quer | Onde se faz |
|---|---|
| **Criar um agente (profile)** | CLI: `hermes profile create <nome>` (a UI não cria) |
| **Escrever/editar o `SOUL.md`** | No **arquivo** (`~/.hermes/SOUL.md` ou `~/.hermes/profiles/<nome>/SOUL.md`) |
| **Editar o `config.yaml`** | No arquivo, ou `hermes config edit` / `hermes config set <chave> <valor>` |
| **Operar (Kanban, Skills, Sessões, Logs, MCP, Pairing)** | Na **UI** (dashboard) |

> Em uma frase: **a UI é o "painel de operação"; a "ficha do agente" (criar profile + SOUL.md) mora em arquivos no `~/.hermes/`.**

### A "personalidade" de um agente (SOUL.md)

```bash
hermes config path     # mostra onde fica a pasta ~/.hermes
```
Abra o `SOUL.md` do profile (no host, em `~/.hermes/SOUL.md` para o default, ou `~/.hermes/profiles/<nome>/SOUL.md` para um cargo). Exemplo de um Hermes "gerente de tráfego":

```markdown
# SOUL

Você é o assistente de tráfego pago da {{SEU_NEGÓCIO}}. Decide e executa com base em números.

- Tom: direto, curto, sem floreio. Sempre confirma o que vai fazer antes de mexer em campanha.
- Nunca gasta acima de R$ 200/dia sem confirmar com o dono.
- Fala português. Trata o dono por "você".
```

### Ajustar configurações (config.yaml)

Você pode editar pelo dashboard ou por comando:
```bash
hermes config set approvals.mode smart      # off | smart | manual (quanto ele pede permissão)
hermes config show                          # conferir tudo
```
Campos úteis para começar: `model` (cérebro), `approvals.mode` (autonomia), `memory` (liga/desliga aprendizado), `mcp_servers` (ferramentas), `delegation` (ajudantes temporários — Seção 7).

### Criar mais agentes (um profile por cargo)

Cada *profile* é um agente isolado — próprio `SOUL.md`, modelo, memória e configurações. É assim que você monta "vários funcionários" na mesma máquina:

```bash
hermes profile create analista        # cria o agente "analista"
hermes profile create gestor          # cria o agente "gestor"
hermes profile list                   # lista todos (mostra modelo de cada um)
hermes profile use analista           # passa a operar nesse agente
```

Exemplo real desta instalação (já tem dois agentes, com **modelos diferentes** por cargo):

```text
 Profile     Model                     Gateway
 ◆default    deepseek/deepseek-v3.2    stopped
  analista   deepseek/deepseek-v4-pro  stopped
```

Depois de `hermes profile use <nome>`, você edita o `SOUL.md` e o `config.yaml` **daquele** profile (ficam em `~/.hermes/profiles/<nome>/`). Assim o "analista" pode usar um modelo mais barato e o "gestor" um mais cuidadoso, cada um com sua personalidade.

> Pense em profiles como **"contas de funcionário"**: cada um tem seu crachá (SOUL.md), seu nível de acesso (MCP/aprovações) e sua memória. Eles trabalham juntos pelo **quadro Kanban** (Seção 7), não por ligação automática entre si.

### 👷 Passo a passo: criar um profile do zero (ex.: "gestor")

> Lembre do prefixo `docker compose exec -it openclaw-vibestack` antes de cada `hermes ...`. Os arquivos ficam no seu Mac, em `~/.hermes/profiles/<nome>/`.

**1. Crie o profile (pela CLI — a UI não faz isso):**
```bash
hermes profile create gestor
```
Isso cria a pasta `~/.hermes/profiles/gestor/` (com `SOUL.md` e `config.yaml` iniciais).

**2. Escreva a personalidade — edite o arquivo no seu Mac:**
Abra `~/.hermes/profiles/gestor/SOUL.md` (VS Code, Finder, etc.) e escreva quem é esse agente. Exemplo:
```markdown
# SOUL

Você é o Gestor de Tráfego da {{SEU_NEGÓCIO}}. Único que ESCREVE no Meta Ads.

- Só executa sob ordem clara (da Estrategista ou do dono). Ordem ambígua: pergunte, não chute.
- Toda campanha nasce PAUSED. Confirme cada ação com o ID retornado.
- Tom: curto e militar. "Pausado. ID=23845." em vez de textão.
```

**3. Entre no profile e escolha o cérebro (modelo) dele:**
```bash
hermes profile use gestor      # passa a operar como "gestor"
hermes model                   # escolhe provedor + modelo SÓ desse profile
```

**4. Ajuste a autonomia e confira (opcional):**
```bash
hermes config set approvals.mode smart   # off | smart | manual
hermes config show                       # confere a config do profile ativo
```
*(Isso edita o `config.yaml` do profile ativo — ou seja, `~/.hermes/profiles/gestor/config.yaml`.)*

**5. Teste o agente:**
```bash
hermes -q "Quais campanhas estão ativas agora?"   # pergunta única, já como 'gestor'
# ou abra a conversa: hermes
```

**6. Volte ao profile padrão quando quiser:**
```bash
hermes profile use default
hermes profile list            # confere qual está ativo (◆) e o modelo de cada um
```

**7. Coloque o profile para trabalhar no quadro (Kanban):**
```bash
hermes kanban create "Pausar conjuntos com ROAS < 1" --assignee gestor
```

> **Repetindo o essencial:** o **passo 1** (criar) e o **passo 2** (SOUL.md) **não** têm botão na UI — são CLI + arquivo. Do passo 3 em diante você pode usar a UI (Configuration/Chat) se preferir.

---

## 7. O "organograma": como montar um time

Você perguntou como criar um **organograma** no Hermes. A resposta precisa:

> **O Hermes tem vários agentes (profiles), sim** — o que ele não tem é o **repasse automático nomeado dentro de uma conversa** (o "organograma vivo" do OpenClaw, em que o Diretor aciona o Analista que aciona o Gestor num único turno). No Hermes, os agentes (profiles) se coordenam por **quadro de tarefas, swarm e delegação**. Se você precisa do repasse automático em tempo real, o **OpenClaw** continua melhor para isso.

Há **três formas** de montar um time no Hermes — da mais simples à mais parecida com um organograma:

### FAQ: multi-agente, profiles e organograma

**"Se não é multi-agente, por que a interface do Hermes tem uma parte de multi-agente?"**
Porque **ele é multi-agente** — cada agente é um **profile**. A área de multi-agente do dashboard é onde você gerencia esses profiles (criar, ver o modelo de cada um, acompanhar quem está executando tarefa). Eu fui impreciso antes ao chamar de "single-agent": o certo é que o Hermes roda **vários agentes (profiles)**; o que muda é a **forma de coordenação** (quadro de tarefas, não repasse automático).

**"E por que ele deixa importar os agentes do OpenClaw, tendo mais de um?"**
Porque a migração (`hermes claw migrate`) traz **cada agente do OpenClaw como um profile no Hermes**. Você tinha 6 agentes na `agency/` → viram (até) 6 profiles. Eles continuam sendo "vários agentes"; só que, no Hermes, a colaboração entre eles passa a ser pelo **Kanban/swarm/delegação** em vez do repasse automático em cadeia. *(O mapeamento exato — 1 profile por agente — confirme com `hermes claw migrate --dry-run`, que mostra o que será criado sem aplicar.)*

**"Então qual é, de fato, a diferença para o OpenClaw?"**
Só uma: **quem dá o próximo passo.** No OpenClaw, um agente **chama outro automaticamente** dentro da mesma conversa (organograma vivo). No Hermes, **você (ou o quadro Kanban, ou o swarm) decide** qual profile pega cada tarefa. Mesma quantidade de agentes; gestão diferente.

### Forma A — Um agente + delegação efêmera (`delegate_task`) ✅ recomendada

O Hermes consegue, **durante uma tarefa**, abrir **ajudantes temporários** para subtarefas (pesquisar, processar arquivos, etc.). Eles:
- nascem **sem memória** (você passa o objetivo e o contexto na hora);
- rodam em paralelo (até 3 por padrão);
- devolvem **só um resumo** e **desaparecem**.

É como um gerente que, num pico, distribui pedaços de um trabalho para freelancers e junta o resultado. Configura-se no `config.yaml`:

```bash
hermes config set delegation.max_concurrent_children 3   # quantos ajudantes ao mesmo tempo
hermes config set delegation.max_spawn_depth 2           # 1 = plano; 2 = ajudante pode ter ajudante
hermes config set delegation.orchestrator_enabled true   # permite o agente "orquestrar" subtarefas
```
**Limite importante:** esses ajudantes são **descartáveis** — não são "o Analista" permanente. Servem para dividir UMA tarefa, não para manter papéis fixos.

### Forma B — Um profile por papel (o mais parecido com organograma)

Crie um *profile* para cada "cargo" e dê a cada um seu `SOUL.md` e suas ferramentas:

```bash
hermes profile create diretor
hermes profile create analista
hermes profile create gestor
```
- O **diretor** fala com você (pelo WhatsApp/Telegram do gateway).
- Como eles são isolados, a "conversa entre cargos" acontece **por mensagem** (um manda tarefa para o outro por um canal/automação) ou **por API** (um chama o `/v1/chat/completions` do outro). Não é tão automático quanto o organograma do OpenClaw, mas dá para orquestrar.

> Use a Forma B quando você quer **papéis realmente separados e persistentes**. É trabalho de integração manual entre eles.

### Forma C — Quadro Kanban visual (`hermes kanban` + aba no dashboard)

O Hermes tem um **quadro Kanban embutido com interface visual** no dashboard. É o jeito mais "gerenciável" de operar um time no Hermes: você cria tarefas, **atribui cada uma a um profile** (= um "cargo", veja a Forma B) e um **dispatcher** roda cada tarefa sozinho, na vez dela. Ótimo para **fila de trabalho** (ex.: "produzir 10 criativos", "auditar 5 campanhas").

Como funciona, em uma frase: **cada tarefa tem um dono (profile) e anda sozinha pelas colunas**; o dispatcher (que vive dentro do `hermes gateway`) pega as tarefas prontas a cada ~60s e executa com o profile atribuído como "trabalhador".

Veja a subseção dedicada abaixo — [Ativar e ver o Kanban na interface](#-ativar-e-ver-o-kanban-na-interface) — para o passo a passo.

### Qual escolher?

| Você quer… | Use |
|---|---|
| Dividir **uma tarefa grande** rapidamente | **A** (delegação) |
| **Cargos separados e permanentes** (organograma de verdade) | **OpenClaw** (`agency/`) — ou **B** (profiles) com integração manual |
| **Fila de tarefas** sendo tocada sozinha | **C** (kanban) |

### 🗂️ Ativar e ver o Kanban na interface

O quadro Kanban **já vem embutido** no Hermes (não precisa instalar nada). No dashboard ele aparece como uma **aba "Kanban"** (logo depois de "Skills" no menu) — é um plugin que já vem na caixa, por isso não está na lista "oficial" de abas. É um quadro **visual e interativo**: você arrasta cartões entre colunas, cria com um "+", clica num cartão para editar, etc.

**As colunas (o caminho de uma tarefa):**
`triage` → `todo` → `scheduled` → `ready` → `running` → `blocked` → `done` (e `archived`). Quem está em `ready` é pego pelo dispatcher e vai para `running` sozinho. `scheduled` = tarefa esperando um horário; `triage` = rascunho que ainda não vai executar (ótimo para testar sem disparar nada).

> ✅ **Validado ao vivo** nesta instalação: a CLI `hermes kanban` tem todos esses comandos (incluindo `init`, `create`, `list`, `stats`, `dispatch`, `archive` e até `swarm` — "trabalhadores em paralelo → verificador → sintetizador"); o **dispatcher roda dentro do gateway** ("ticando" a cada 60s — o subcomando `daemon` antigo está **deprecado**); e o **plugin visual existe** em `/opt/hermes-agent/plugins/kanban/dashboard/` (é ele que desenha a aba "Kanban" no dashboard).

#### Passo a passo (ativar e ver funcionando)

**1. Inicialize o quadro (uma única vez)** — cria o banco do Kanban:
```bash
hermes kanban init
```

**2. Garanta que o `gateway` está rodando** — é ele que "tica" o dispatcher a cada ~60s e executa as tarefas. *(Neste projeto o entrypoint já sobe o gateway; para conferir: `hermes gateway status`.)*

**3. Abra o dashboard e a aba Kanban:**
- Mac/Windows: `http://127.0.0.1:9119` → clique em **"Kanban"** (após "Skills").
- VPS: `ssh -N -L 9119:127.0.0.1:9119 root@SEU_VPS_IP` e abra `http://127.0.0.1:9119`.

**4. Crie uma tarefa** — pela interface (botão **"+"** no topo de uma coluna) **ou** pela CLI, atribuindo a um *profile* (o "cargo" que vai executar):
```bash
hermes kanban create "Gerar 3 criativos 9:16 da promo de junho" --assignee criativo
hermes kanban create "Auditar campanhas com ROAS < 1" --assignee analista
hermes kanban list           # ver as tarefas e seus status
```

**5. Veja andar sozinho** — em até ~60s o dispatcher pega as tarefas em `ready`, move para `running` e executa com o profile atribuído. No quadro, os cartões se movem **ao vivo** (atualização em tempo real). Você pode:
- **arrastar** um cartão entre colunas (ex.: puxar de `triage` para `ready` para liberar a execução);
- clicar no cartão para abrir o **painel lateral** (editar título, responsável, descrição, dependências, comentários);
- usar o **"+"** para criar direto numa coluna; e fazer **ações em lote** (selecionar vários e mudar status/arquivar).

**6. Acompanhar pela CLI** (alternativa à UI):
```bash
hermes kanban show <id>      # detalhes de uma tarefa
hermes kanban watch          # acompanha em tempo real no terminal
hermes kanban stats          # visão geral
hermes kanban dispatch --dry-run   # ver o que o dispatcher faria, sem executar
```

#### Comandos úteis do `hermes kanban`

| Comando | O que faz |
|---|---|
| `init` | Cria o quadro (uma vez). |
| `create "<título>" --assignee <profile>` | Nova tarefa atribuída a um cargo. Aceita `--priority`, `--skill <nome>`, `--triage`, `--parent <id>`. |
| `list` / `show <id>` | Listar / detalhar tarefas. |
| `decompose <id>` | Quebra uma tarefa grande em subtarefas. |
| `specify <id>` | Detalha uma tarefa que entrou como rascunho (`triage`). |
| `dispatch [--dry-run] [--max N]` | Roda o despachante manualmente (normalmente é automático). |
| `assign <id> <profile>` / `block`/`unblock` / `promote` / `complete` / `archive` / `comment` | Mover/gerir tarefas. |
| `boards` | Gerencia **quadros** (um por projeto/fluxo). |
| `swarm` | Cria um "enxame": vários cargos em paralelo → verificador → sintetizador. |

#### Exemplos práticos (copiar e colar)

> Lembre do prefixo `docker compose exec -it openclaw-vibestack` antes de cada `hermes ...`.

**1) Tarefa simples, atribuída a um cargo (profile):**
```bash
hermes kanban create "Resumir o desempenho das campanhas de ontem" --assignee analista
```

**2) Tarefa detalhada (corpo, prioridade e uma skill):**
```bash
hermes kanban create "Gerar 3 criativos 9:16 da promo de junho" --assignee criativo --body "Formato Reels; CTA 'Saiba mais'." --priority 1 --skill criar-criativo
```

**3) Criar como rascunho (não dispara) e liberar depois:**
```bash
hermes kanban create "Auditar campanhas com ROAS < 1" --assignee analista --triage
hermes kanban list                  # veja o id (ex.: t_ab12cd34)
hermes kanban promote t_ab12cd34    # move para 'ready' -> o dispatcher pega em ~60s
```

**4) Quebrar uma tarefa grande em subtarefas:**
```bash
hermes kanban create "Lançar campanha de Dia dos Pais" --assignee gestor
hermes kanban decompose <id>        # cria as subtarefas filhas
```

**5) Criar um QUADRO novo (um board por projeto/cliente):**
```bash
hermes kanban boards --help         # mostra os subcomandos de quadro (create/list/use…)
hermes kanban boards create criativos          # cria o quadro "criativos"
# depois, mire um quadro específico com --board:
hermes kanban --board criativos create "Banner da home" --assignee criativo
hermes kanban --board criativos list
```
> Cada **board** é um quadro independente (ex.: um por cliente). O `--board <slug>` diz em qual quadro o comando age; sem ele, usa o quadro padrão. *(Confirme o nome exato do subcomando de criação na sua versão com `hermes kanban boards --help`.)*

**6) Enxame (swarm) — vários cargos numa meta só:**
```bash
hermes kanban swarm --help          # opções para fan-out (trabalhadores → verificador → sintetizador)
```

#### Onde fica salvo

Tudo em `/root/.hermes/kanban*` (persistente): o banco `kanban.db`, as pastas de trabalho de cada tarefa (`kanban/workspaces/<id>/`, apagadas ao concluir) e os logs (`kanban/logs/`).

#### Ajustes opcionais (config)

No `config.yaml` você pode afinar o comportamento (não é obrigatório):
```bash
hermes config set kanban.dispatch_interval_seconds 60   # de quanto em quanto o dispatcher roda
hermes config set kanban.auto_decompose true            # quebra tarefas grandes sozinho
hermes config set dashboard.kanban.lane_by_profile true # mostra uma "raia" por cargo na coluna "running"
```

> **Dica de organograma:** Kanban + um **profile por cargo** (Forma B) é o mais perto de um "time com fila de trabalho" que o Hermes oferece — cada tarefa tem um responsável e roda sozinha. Para hierarquia de **decisão/aprovação** (Diretor aprova, Gestor executa), o OpenClaw ainda é mais direto.

### 🎬 Como as tasks funcionam na prática (fluxo temporal de uma agência)

Aqui é onde tudo se junta. Vamos ver, **minuto a minuto**, uma agência de tráfego (cada cargo = um *profile*) usando o Kanban para **lançar uma campanha no Meta Ads com criativos**.

#### Primeiro, o conceito de "task" em 30 segundos

Uma **task** (tarefa) é um **cartão de pedido** com: um **título**, um **dono** (`--assignee <profile>` = o cargo que vai executar), um **status** (a coluna) e, opcionalmente, **dependências** (espera outra task terminar). O **dispatcher** (dentro do gateway, a cada ~60s) pega as tasks que estão em `ready`, entrega ao profile dono — que roda **isolado**, usa suas ferramentas MCP, e marca a task como `done`. Tasks com dependência pendente ficam `blocked` até a dependência fechar.

#### Os três jeitos de criar trabalho — e quando usar cada um

| Jeito | O que faz | Analogia | Quando usar |
|---|---|---|---|
| **`create`** | Cria **uma** task para **um** cargo | Passar **um** pedido a **um** funcionário | Trabalho pontual |
| **`decompose`** | Quebra uma task em **partes diferentes** que se **somam** | Dividir um projeto em **etapas** entre vários | "Lançar campanha" = analisar + escrever + criar arte + publicar |
| **`swarm`** | Manda **vários** tentarem a **mesma** meta em paralelo → um **verifica** → um **sintetiza** o melhor | Pedir **3 propostas**, conferir e escolher a melhor | Gerar variações criativas e ficar com a melhor |

> Em uma frase: **decompose = dividir em pedaços diferentes; swarm = várias tentativas da mesma coisa, e escolher a melhor.**

#### A linha do tempo (cenário real: promo de Dia dos Pais)

Cargos (profiles) já criados: `diretor`, `analista`, `estrategista`, `copywriter`, `criativo`, `gestor`. Quadro: `campanhas`.

**T+0 — Você joga o pedido no quadro** (uma task-mãe para a Estrategista):
```bash
hermes kanban --board campanhas create "Lançar promo de Dia dos Pais (seu produto)" --assignee estrategista
```

**T+0 — A Estrategista (ou você) decompõe em etapas com dependências.** Quem publica (Gestor) só pode rodar **depois** que texto e arte ficarem prontos:
```bash
hermes kanban --board campanhas create "Ler performance 14d e apontar os melhores ângulos" --assignee analista
hermes kanban --board campanhas create "Escrever 3 textos (headline/primary/description)"   --assignee copywriter
hermes kanban --board campanhas create "Produzir 3 criativos 9:16 da promo"                  --assignee criativo
# a task do Gestor depende das duas anteriores (texto + arte):
hermes kanban --board campanhas create "Montar campanha PAUSED + ad set + anúncio" --assignee gestor --parent <id_copy> --parent <id_criativo>
```
*(`--parent` cria a dependência; dá no mesmo que `hermes kanban link <pai> <filho>`.)*

**T+1min — primeiro "tick" do dispatcher.** Ele vê 3 tasks em `ready` (analista, copywriter, criativo — sem dependências) e dispara **em paralelo**, cada profile como um trabalhador isolado:
- 🔎 **Analista** usa o MCP `meta-ads` (só leitura): `get_insights`, `list_campaigns` → entrega "os ângulos X e Y converteram melhor".
- ✍️ **Copywriter** escreve as 3 variações e marca `done`.
- 🎬 **Criativo** dispara um **swarm** para a arte (detalhe abaixo).
- 🛠️ **Gestor** continua `blocked` (faltam as dependências). 🎯 **Diretor** idem.

**T+1min (dentro do Criativo) — o swarm da arte:**
```bash
hermes kanban --board campanhas swarm "Gerar 3 conceitos de criativo 9:16 da promo" --assignee criativo
```
O swarm monta sozinho:
1. **3 workers em paralelo** — cada um gera um conceito (MCP `higgsfield` `generate_image` / `media-editor` `image_fit`+`image_overlay`).
2. **1 verificador** — roda `probe(validate_for="meta_image_story")` e descarta o que estiver fora das specs do Meta.
3. **1 sintetizador** — escolhe o melhor e finaliza com `finalize_for_meta(...)` → gera o arquivo em `/root/.openclaw/workspace/_shared/creatives/`.

Resultado: **1 arquivo final aprovado**, o caminho dele volta como resultado da task.

**T+~6min — texto e arte ficam `done`.** Como a task do Gestor dependia das duas, ela **destrava** (`blocked → ready`).

**T+~7min — próximo tick: o Gestor executa** (MCP `meta-ads`, escrita): `create_campaign` (status **paused**, por segurança) → `create_ad_set` → `create_creative` (usando o `path` do criativo + os textos do copy) → `create_ad`. Confirma com os **IDs** e marca `done`.

**T+~8min — a task do Diretor destrava** → ele consolida tudo e **te avisa no seu canal** (WhatsApp/Telegram), com o resumo e os IDs. *(A entrega no canal é configurável por task — ver `hermes kanban notify-subscribe` / roteamento de entrega.)*

#### O quadro evoluindo (o que você vê na aba Kanban)

```
            T+0min                         T+1min                        T+7min
ready    │ analista, copy, criativo │   (vazio)                  │  gestor
running  │                          │   analista, copy, criativo │  gestor
blocked  │ gestor, diretor          │   gestor, diretor          │  diretor
done     │                          │                            │  analista, copy, criativo
```
No dashboard os cartões se movem **ao vivo**; no terminal você acompanha com:
```bash
hermes kanban --board campanhas watch     # stream ao vivo
hermes kanban --board campanhas stats      # contagem por status e por cargo
```

#### O paralelo com a sua agência do OpenClaw

| Na agência (OpenClaw) | Vira, no Kanban do Hermes |
|---|---|
| Estrategista despacha o caso | Task-mãe atribuída ao profile `estrategista` |
| Cada cargo recebe sua parte | `decompose` → uma task por cargo |
| "Gestor só publica após aprovação" | Dependência (`--parent`) deixa a task do gestor `blocked` até as outras |
| Criativo entrega 1 peça (não 3 "por garantia") | `swarm` gera 3, **verifica** e entrega **1** |
| Diretor avisa o dono | Task final do `diretor` com entrega no seu canal |

> A grande diferença que você já conhece: no OpenClaw esse encadeamento é **automático dentro de um turno**; no Kanban do Hermes ele acontece pelo **quadro + dependências + dispatcher** (cada etapa numa sessão isolada). O resultado de negócio é o mesmo; a "engrenagem" é o quadro.

---

## 8. Transferir do OpenClaw para o Hermes

Há duas camadas para "transferir": (1) **configurações/ferramentas/segredos** (automático) e (2) **a personalidade dos agentes** (manual, porque o modelo de organização é diferente).

### 8.1 Migração automática de configurações — `hermes claw migrate`

O Hermes traz um comando dedicado para importar do OpenClaw:

```bash
hermes claw migrate --dry-run                 # SIMULA: mostra o que viria, sem aplicar
hermes claw migrate --preset user-data        # traz dados do usuário (memórias, sessões…)
hermes claw migrate --preset full --migrate-secrets   # traz tudo, inclusive chaves/segredos
```
- ⭐ **Sempre comece com `--dry-run`** para ver o que será trazido antes de aplicar.
- `--preset full` é o mais abrangente; `--migrate-secrets` inclui credenciais (use com cuidado).

Isso traz modelo/provedor, MCP, dados — e **cada agente do OpenClaw como um profile no Hermes** (por isso "vem mais de um"). Rode o `--dry-run` para ver exatamente quais profiles seriam criados antes de aplicar. O que **não** vem é o "repasse automático em cadeia" do organograma do OpenClaw — no Hermes os profiles passam a se coordenar por Kanban/swarm/delegação.

### 8.2 Ajustar a "personalidade" depois de migrar (manual)

Cada agente vira um profile com seu `SOUL.md`. Se quiser refinar (ou montar do zero em vez de migrar), o mapeamento dos arquivos do OpenClaw é:

| No OpenClaw (`agency/<agente>/`) | Vira, no Hermes |
|---|---|
| `IDENTITY.md` + `SOUL.md` | Conteúdo do **`SOUL.md`** do Hermes (junte os dois) |
| `USER.md` | Trechos do `SOUL.md` (com quem ele fala, tom) ou do perfil de usuário (`memories/USER.md`) |
| `AGENTS.md` (fluxo, regras, "não faça") | Vira **regras no `SOUL.md`** + uma **skill** (Seção 10) com o procedimento passo a passo |
| `TOOLS.md` (quais MCP usar) | Já é resolvido pelo `config.yaml` (`mcp_servers`) — o Hermes vê as ferramentas conectadas |

**Duas estratégias práticas:**
- **Quer UM assistente forte?** Junte o melhor dos 6 num único `SOUL.md` e transforme os procedimentos (analisar, criar campanha, gerar criativo) em **skills**. O Hermes escolhe a skill certa na hora.
- **Quer manter os 6 papéis separados?** Crie **um profile por agente** (Seção 7, Forma B) e cole o `SOUL.md` correspondente em cada um.

> Lembre-se: os prompts do OpenClaw que você baixou já estão **genéricos com placeholders** (`{{DONO}}`, `{{PRODUTO_1}}`…). Ao migrar para o Hermes, troque os placeholders pelos seus valores reais no `SOUL.md`.

---

## 9. Crons e "heartbeats"

Aqui está uma **boa notícia**: o Hermes tem **agendamento embutido** (cron). Você **não** precisa de ferramenta externa.

### Como funciona (o "heartbeat")

O `hermes gateway` (que neste projeto já está rodando) **"bate o coração" a cada 60 segundos**: a cada batida ele verifica se há tarefa agendada vencida e, se houver, executa numa **sessão nova e isolada** (sem misturar com outras conversas). Esse tique de 60s é o "heartbeat" do Hermes.

> ⚠️ **Pré-requisito:** o **gateway precisa estar rodando** para os crons dispararem. Neste projeto o entrypoint já sobe o gateway — então está coberto.

### Criar uma tarefa agendada

Pelo chat (durante uma conversa):
```
/cron add "every 2h" "Verifique o status das campanhas e me avise se algo caiu"
```
Pela CLI:
```bash
hermes cron create "every 2h" "Resumo das campanhas ativas e alertas"
hermes cron create "0 9 * * *" "Relatório diário às 9h"     # expressão cron clássica
hermes cron create "30m" "Tarefa única daqui a 30 minutos"  # atraso relativo (roda uma vez)
```

**Formatos de horário aceitos:**
- **Intervalo:** `every 30m`, `every 2h`, `every 1d` (repete).
- **Expressão cron:** `0 9 * * *` (todo dia às 9h), `0 */6 * * *` (a cada 6h).
- **Atraso relativo:** `30m`, `2h`, `1d` (dispara uma vez).
- **Data/hora ISO:** um horário específico.

### Gerenciar os agendamentos

```bash
hermes cron list           # ver todos
hermes cron status         # estado do agendador
hermes cron run <id>       # rodar agora, na mão (teste)
hermes cron pause <id>     # pausar / hermes cron resume <id> para voltar
hermes cron remove <id>    # apagar
```
Os jobs ficam em `/root/.hermes/cron/` (persistente — sobrevivem a reinício).

### Recursos avançados (cite no curso como "dá para crescer")

- **Anexar uma skill** ao job: `/cron add "every 1h" "..." --skill nome-da-skill`.
- **Encadear jobs** (um usa o resultado do anterior) via `context_from`.
- **Entregar o resultado num canal** (te mandar no WhatsApp/Telegram quando terminar).
- **Portão `wakeAgent`**: deixa o job checar uma condição barata **antes** de acordar o cérebro (o modelo), economizando custo quando não há nada a fazer.

> **Comparação rápida:** tanto o OpenClaw (`openclaw cron`) quanto o Hermes (`hermes cron`) têm agendador. No Hermes ele é "ticado" pelo gateway a cada 60s e cada disparo roda numa sessão limpa.

---

## 10. Memória e Skills

Este é **o diferencial** do Hermes — vale uma aula só.

### Memória (ele lembra de você)

O Hermes mantém, em `/root/.hermes/memories/`:
- **`USER.md`** — quem é você (preferências, contexto do negócio).
- **`MEMORY.md`** — observações que ele juntou ao longo do tempo.

Esses arquivos entram no início de cada conversa (como um "resumo do que eu sei sobre você"). Além disso, ele **indexa todas as conversas** e consegue **buscar no próprio histórico** ("o que combinamos sobre a campanha de junho?"). Ligar/conferir:
```bash
hermes memory status
hermes memory setup      # configura memória (inclusive opções avançadas de busca semântica)
```

### Skills (ele aprende procedimentos)

Uma **skill** é um documento de "como fazer X" que o agente carrega **só quando precisa** (economiza tokens). É um arquivo `SKILL.md` com um cabeçalho e instruções. Exemplo do conceito:

```markdown
---
name: criar-campanha-meta
description: Passo a passo para abrir uma campanha de tráfego no Meta Ads
---
# Criar campanha no Meta Ads
## Quando usar
Quando o dono pedir uma campanha nova.
## Passos
1. Confirmar objetivo e orçamento.
2. Usar a tool create_campaign (status=paused).
3. ...
```
O mais interessante: **o próprio Hermes cria e melhora skills com o uso**. Você também pode instalar prontas:
```bash
hermes skills browse           # ver disponíveis
hermes skills install <id>     # instalar
hermes skills list             # ver instaladas
```
Use skills como **"procedimentos da empresa (POPs)"**: você ensina uma vez, ele repete sempre igual.

---

## 11. Glossário e checklist

### Glossário rápido

- **Gateway** — o processo que conecta os mensageiros (WhatsApp/Telegram) **e** sobe a API; também é quem dispara os crons (tique de 60s).
- **Profile** — uma instância isolada do Hermes (sua "conta de funcionário"). Vários profiles = vários agentes separados.
- **Delegação (`delegate_task`)** — ajudantes temporários para subtarefas; somem ao terminar.
- **Skill** — procedimento que o agente carrega sob demanda; ele aprende sozinho.
- **Memória** — `USER.md` + `MEMORY.md` + busca no histórico.
- **Approvals (`mode`)** — quanto o agente pede permissão antes de agir: `off` (faz tudo), `smart` (pede no que é arriscado), `manual` (pede sempre).
- **MCP** — as ferramentas/integrações (Meta Ads, vídeo, WhatsApp, geração de imagem).

### Checklist do primeiro dia com Hermes

1. [ ] Abrir o dashboard (`http://127.0.0.1:9119`) ou rodar `hermes` no terminal.
2. [ ] `hermes model` — escolher provedor e modelo.
3. [ ] `hermes mcp list` — confirmar as ferramentas conectadas.
4. [ ] Editar o `SOUL.md` — dar personalidade e regras ao agente.
5. [ ] `hermes config set approvals.mode smart` — definir o nível de autonomia.
6. [ ] Criar um cron de teste: `hermes cron create "30m" "me mande um oi"` e depois `hermes cron list`.
7. [ ] (Se vindo do OpenClaw) `hermes claw migrate --dry-run` para ver o que dá para importar.

---

### Observações de precisão (para você, instrutor)

Itens abaixo foram verificados na documentação oficial do Hermes, mas podem variar de versão — confira na sua instalação antes de gravar:
- A **API server** é habilitada por **variáveis de ambiente** (`API_SERVER_ENABLED`, `API_SERVER_KEY`, `API_SERVER_PORT`), não por um bloco no `config.yaml`. Neste projeto o entrypoint já define a key e roda o gateway.
- O **nome exato do modelo** padrão muda com o tempo — trate qualquer string de modelo como **exemplo**.
- Detalhes de flags de `hermes cron` / `hermes kanban` / `hermes claw migrate` podem ter pequenas diferenças por versão: rode `hermes <comando> --help` na sua instalação para a lista exata.
- O Hermes **tem vários agentes** (cada um é um *profile*: `hermes profile create/list/use`). O que ele **não** tem é o repasse automático em cadeia dentro de uma conversa (o "organograma vivo" do OpenClaw) — os profiles se coordenam por Kanban/swarm/delegação. (Não existe `hermes agent create`; o equivalente é `hermes profile create`.)
