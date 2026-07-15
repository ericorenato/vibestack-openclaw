# Google Ads API — passo a passo do zero (material de aula)

Guia real de como conectamos o projeto (OpenClaw + Hermes) a uma conta de
**produção** do Google Ads, explicado **como se fosse para um leigo**. Diferente da
Meta (que tem a CLI oficial `meta`), o **Google Ads não tem CLI oficial** — a gente
fala com a API pela biblioteca oficial `google-ads`, envelopada no MCP `google-ads`
e no CLI `googleads`.

> **Segurança:** este arquivo é versionado. Nunca coloque aqui developer token,
> client secret ou refresh token reais — eles vivem só no `.env` (gitignored).
> Onde aparece `<ASSIM>` é um valor que você preenche.

---

## 🧭 Visão geral — por que são tantas peças?

Pra um programa (o nosso MCP/CLI) mexer nas suas campanhas sozinho, o Google exige
**3 identidades diferentes**. É normal confundir. Pensa nisso como o encanamento de
uma casa: cada peça existe por um motivo.

| Peça | O que é | Pergunta que responde |
|---|---|---|
| **MCC** (conta administradora) | A "gerência" que controla contas de anúncio | *"Quem é o dono/gestor?"* |
| **Conta de anúncios** | Onde as campanhas realmente rodam | *"Onde estão as campanhas?"* |
| **Developer Token + OAuth** | As chaves que o robô usa pra entrar | *"Com que credencial o programa entra?"* |

**Ordem geral:** MCC → criar/vincular conta de anúncios → developer token → **pedir
Basic access** (com design-doc, esperar ~1-3 dias) → projeto no Google Cloud + OAuth
→ refresh token → `.env` → testar.

---

## Pré-requisitos
- Uma conta Google que já administra (ou vai administrar) o Google Ads.
- O container do projeto no ar (`docker compose up -d openclaw-vibestack`).

---

## 1. Criar a conta ADMIN (MCC) — e por quê

**MCC** = *My Client Center* / "Conta de Administrador". É como o **molho de chaves
do síndico**: ela não tem campanha nenhuma, mas comanda várias contas de anúncio por
baixo.

**Por que você PRECISA dela:** a chave da API (o *developer token*) **só nasce dentro
de uma MCC**. Uma conta de anúncios comum nunca te dá essa chave. Sem MCC, não existe
automação — ponto.

**Como criar:**
1. Abra https://ads.google.com/home/tools/manager-accounts → **"Criar uma conta de administrador"**.
2. Entre com o Google que vai ser o dono, dê um nome (ex.: `Érico Ads`), país (Brasil) e moeda (BRL).
3. Anote o **ID da MCC** (topo, formato `123-456-7890`). No projeto é o `GOOGLE_ADS_LOGIN_CUSTOMER_ID` (sem hífens).

> 💡 Como saber que é MCC mesmo: ela tem o menu **"Contas"** (lista de clientes) e
> **não** tem "Campanhas"/"Faturamento" no menu principal como a conta comum.

## 2. A conta de ANÚNCIOS (onde as campanhas vivem)

Essa é a conta "normal" do Google Ads: campanhas, orçamento, faturamento. **Por que
separada da MCC:** a MCC é o síndico; a conta de anúncios é o apartamento. O síndico
administra, mas o dinheiro e as campanhas ficam no apartamento.

- **Você já tem uma?** Ótimo — pule pra vinculação (passo 3).
- **Não tem?** Dentro da **MCC** → **Contas → "+" → "Criar nova conta"**. Preencha nome, fuso, moeda.

## 3. Associar (vincular) a conta à MCC — e por quê

**Por que:** o token vive na MCC. Pra ele ter permissão de mexer na sua conta de
anúncios, a conta precisa estar **pendurada embaixo da MCC**. Sem isso, a API responde
`USER_PERMISSION_DENIED` (acesso negado). É um **convite + aceite**, como adicionar amigo.

1. Dentro da **MCC** → **Contas → "+" → "Vincular conta existente"**.
2. Digite o **ID da conta de anúncios** (`123-456-7890`) e envie o convite.
3. Troque pra **conta de anúncios** no seletor de contas (canto superior).
4. **Aceite o convite** — nas 🔔 Notificações, ou em *Adm. → Acesso e segurança → Administradores*.
5. Anote o **ID da conta de anúncios** = `GOOGLE_ADS_CUSTOMER_ID` (sem hífens). É **diferente** do ID da MCC.

## 4. Developer Token + pedir Acesso Básico (o passo que demora)

Pegadinha que confunde todo mundo: **existem níveis de acesso.** O token nasce fraco
e você precisa pedir o nível que **escreve**.

| Nível | O que faz | Serve pra você? |
|---|---|---|
| **Test** | Só mexe em contas de teste (fake) | ❌ Não |
| **Analytics** (nasce aqui) | **Lê** contas reais, mas **não escreve** | ⚠️ Só metade |
| **Basic** | **Lê + escreve** produção (15 mil operações/dia) | ✅ **É esse que você quer** |
| Standard | Volume gigante | Só ferramentas grandes |

**Onde pegar o token:**
1. Dentro da **MCC** → engrenagem **⚙️ (Adm.) → Configuração → Central de API** (*API Center*).
2. Copie o **Token de desenvolvedor** = `GOOGLE_ADS_DEVELOPER_TOKEN`. Ele começa em "Analytics".

**Como pedir o Acesso Básico (o formulário):** na mesma Central de API, clique
**"Solicitar acesso básico"**. Respostas que usamos (ajuste ao seu caso):
- **ID da MCC:** `<ID da MCC>`
- **Tem representante do Google?** → **No**
- **Site da empresa:** `<https://seusite.com>` (ex.: `https://ericorenato.com.br`)
- **Modelo de negócio:** *"Gestão das próprias campanhas de Search via API (leitura e
  escrita), em fluxo assistido por IA, em infraestrutura própria, apenas em contas
  próprias/geridas."*
- **📄 Documento de design (obrigatório):** eles exigem um documento explicando **o que
  seu sistema faz com a API**. Use o modelo desta pasta →
  [`google-ads-api-design-doc.rtf`](google-ads-api-design-doc.rtf). Só adaptar e enviar.
- **Quem terá acesso?** → **"Internal users - employees only"**.
- **Usa com ferramenta de terceiros?** → **No**. **App Conversão/Remarketing?** → **No**.
- **Tipos de campanha:** `Search`. **Capacidades:** **Campaign Creation, Campaign Management, Reporting**.

**⏳ A espera:**
- Sai em geral em **~1 a 3 dias úteis**.
- **Enquanto não aprova, a leitura já funciona** (nível Analytics) — listar campanhas,
  ver relatórios. **O que não funciona é criar/pausar/editar.**
- Às vezes respondem por e-mail pedindo esclarecimento — responda rápido pra não reiniciar a fila.

> **Resumo dos níveis:** Test = só teste · **Analytics = lê produção, não escreve** ·
> **Basic = lê + escreve produção** (15k ops/dia) · Standard = mais.

## 5. Projeto no Google Cloud + OAuth (as "chaves de entrada")

**Por que ISSO ainda, se já tenho o token?** O token diz *"esse programa pode falar
com a API"*, mas o Google também quer saber *"quem autorizou esse programa a mexer NA
MINHA conta?"*. Essa segunda resposta é o **OAuth**, e ele mora no **Google Cloud**
(lugar separado do Google Ads).

> Pensa assim: o **token** é o crachá da empresa; o **OAuth** é a sua assinatura autorizando.
> A "API key" do Google Ads, na prática, são **três coisas juntas**: Developer Token +
> Client ID + Client Secret — não é uma chave única só.

1. https://console.cloud.google.com → **"Criar projeto"** (ex.: `Hermes Ads`).
2. **Habilite a Google Ads API:** busque "Google Ads API" no topo → **Ativar**.
   *(ou APIs e serviços → Biblioteca → "Google Ads API" → Ativar.)*
3. **Tela de consentimento (OAuth / Google Auth Platform):**
   - **Branding:** nome do app (ex.: `Érico Ads Manager`) + e-mail de suporte.
   - **Público-alvo:** tipo **External** e **PUBLIQUE ("Em produção")**.
     > ⚠️ Se ficar em "Testing", o refresh token **expira em 7 dias** e a conexão cai
     > sozinha. Publicado, não expira. A scope do Google Ads é "restrita": ao autorizar
     > você verá *"O Google não verificou este app"* → **Avançado → Acessar o app**
     > (ok até 100 usuários, sem verificação formal — é seu próprio app, é seguro).
4. **Cliente OAuth:** **Credenciais → Criar credenciais → ID do cliente OAuth → tipo
   "App para computador" (Desktop app)** → **Criar**. Copie **as duas coisas**:
   - `GOOGLE_ADS_CLIENT_ID` (termina em `.apps.googleusercontent.com`)
   - `GOOGLE_ADS_CLIENT_SECRET` (começa com `GOCSPX-`) — em **Baixar o JSON** ou abrindo o cliente.

## 6. Gerar o Refresh Token (a autorização permanente)

Client ID e Secret sozinhos não bastam — falta você **assinar a autorização uma vez**.
Isso gera o **refresh token**, que deixa o robô entrar pra sempre sem pedir senha de novo.
Com `CLIENT_ID` e `CLIENT_SECRET` já no `.env` e o container no ar:

```bash
docker compose exec -it openclaw-vibestack googleads auth
```
1. Ele imprime uma **URL** → abra no navegador **logado na conta que administra o
   Google Ads** (a mesma da MCC/campanhas) → autorize (passe pelo aviso de app não verificado).
2. O navegador tenta abrir `http://localhost:8080/?code=...` e **falha (é esperado)**
   → copie a **URL inteira** da barra e cole no terminal.
3. Ele imprime `GOOGLE_ADS_REFRESH_TOKEN=...`.

> ⚠️ **Qual e-mail:** o contato da API/formulário pode ser qualquer e-mail seu; mas
> quem **autoriza** o OAuth aqui tem que ser o Google que **acessa o Google Ads**,
> senão dá `USER_PERMISSION_DENIED`.

## 7. Juntar tudo no `.env`

Todas as peças viram 6 variáveis:
```bash
GOOGLE_ADS_DEVELOPER_TOKEN=<token da MCC (Basic access), passo 4>
GOOGLE_ADS_CLIENT_ID=<...apps.googleusercontent.com, passo 5>
GOOGLE_ADS_CLIENT_SECRET=<GOCSPX-..., passo 5>
GOOGLE_ADS_REFRESH_TOKEN=<gerado no passo 6>
GOOGLE_ADS_LOGIN_CUSTOMER_ID=<ID da MCC, SEM hifens>
GOOGLE_ADS_CUSTOMER_ID=<ID da conta de anúncios, SEM hifens>
```
Recrie o container pra propagar:
```bash
docker compose up -d openclaw-vibestack
```

## 8. Testar

```bash
docker compose exec openclaw-vibestack googleads accounts     # contas acessíveis
docker compose exec openclaw-vibestack googleads campaigns    # campanhas reais
docker compose exec openclaw-vibestack googleads insights --preset LAST_30_DAYS
```
Pelos **agentes** (OpenClaw/Hermes) é só pedir: *"liste minhas campanhas do Google Ads"*.

**Escrita** (libera com o Basic access aprovado):
```bash
docker compose exec openclaw-vibestack googleads create-campaign --name "Teste API" --daily 50
# nasce PAUSED; confira no painel e depois: googleads remove-campaign <id>
```

---

## 🗺️ Resumo em uma linha

> **MCC** (dá o token) → **conta de anúncios** (tem as campanhas) → **vincular** as duas
> → **pedir Basic access** com o design-doc e esperar ~1-3 dias → **Google Cloud** cria
> as chaves OAuth → **gerar refresh token** → colar no `.env` → testar.

## ⚠️ Os 3 erros que 90% das pessoas cometem

| Erro | Sintoma | O que era |
|---|---|---|
| Deixar OAuth em "Testing" | Conexão cai depois de ~7 dias / `invalid_grant` | Faltou **publicar** o app (passo 5.3) e refazer o refresh token |
| IDs com hífen no `.env` | `USER_PERMISSION_DENIED` | Tirar os hífens dos dois IDs |
| Autorizar com o Google errado | `USER_PERMISSION_DENIED` | Autorizar com o dono do Ads (passo 6); conta vinculada na MCC |
| Token ainda em Analytics/Test | `DEVELOPER_TOKEN_NOT_APPROVED` | Esperar o **Basic access** (passo 4) |

## Referências
- MCP: `middleware/google_ads_cli_mcp.py` · CLI: `middleware/googleads_cli.py`
- Design-doc modelo: [`google-ads-api-design-doc.rtf`](google-ads-api-design-doc.rtf)
- GAQL: https://developers.google.com/google-ads/api/docs/query/overview
- SDK: https://pypi.org/project/google-ads/
