# Google Ads API — passo a passo do zero (material de aula)

Guia real de como conectamos o projeto (OpenClaw + Hermes) a uma conta de
**produção** do Google Ads. Diferente da Meta (que tem a CLI oficial `meta`), o
**Google Ads não tem CLI oficial** — a gente fala com a API pela biblioteca
oficial `google-ads`, envelopada no MCP `google-ads` e no CLI `googleads`.

> **Segurança:** este arquivo é versionado. Nunca coloque aqui developer token,
> client secret ou refresh token reais — eles vivem só no `.env` (gitignored).
> Onde aparece `<ASSIM>` é um valor que você preenche.

Ordem geral: **MCC → vincular conta → developer token (Basic access) → projeto no
Google Cloud + OAuth → refresh token → `.env` → testar.**

---

## Pré-requisitos
- Uma conta Google que já administra (ou vai administrar) o Google Ads.
- O container do projeto no ar (`docker compose up -d openclaw-vibestack`).

---

## 1. Criar a conta de administrador (MCC)
O **developer token** (chave da API) **só existe numa conta MCC** (Manager
Account / "Minha Central de Clientes") — nunca numa conta de anúncios comum.

1. Abra https://ads.google.com/home/tools/manager-accounts → **Criar uma conta de administrador**.
2. Logue com o Google que vai administrar, dê um nome (ex.: `Sua Agência`), país e moeda.
3. Anote o **ID da MCC** (canto superior, formato `123-456-7890`). No projeto chamamos de `GOOGLE_ADS_LOGIN_CUSTOMER_ID` (sem hífens).

> Como saber se está na MCC: ela tem o menu **Contas** (lista de clientes) e
> **não** tem Campanhas/Faturamento como a conta comum.

## 2. Vincular a conta real de campanhas sob a MCC
Pra MCC (e o token dela) operar a sua conta de anúncios pela API:

1. Dentro da **MCC** → menu **Contas** → **+** → **Vincular conta existente**.
2. Informe o **ID da conta real** (`123-456-7890`) → envia o convite.
3. Troque pra conta real no seletor de contas → **aceite o convite** (nas
   Notificações ou em *Adm. → Acesso e segurança → Administradores*).
4. Anote o **ID da conta real** = `GOOGLE_ADS_CUSTOMER_ID` (sem hífens).

## 3. Developer token + Acesso Básico
1. Entre na **MCC** → **Adm. (engrenagem) → Configuração → Central de API**
   (ou *Ferramentas e Configurações → Configuração → Central de API*).
2. Copie o **Token de desenvolvedor** = `GOOGLE_ADS_DEVELOPER_TOKEN`.
3. **Nível de acesso:** o token nasce em **"Acesso às Análises"** (Analytics) —
   isso **lê** contas reais, mas **não escreve** (não cria/pausa campanha).
4. Clique em **Solicitar acesso básico** e preencha o formulário. Respostas que
   usamos (ajuste ao seu caso):
   - MCC ID: `<ID da MCC>`
   - Relação com representante do Google: **No**
   - Site da empresa: `<https://seusite.com>`
   - Modelo de negócio: agência/SEM que gerencia campanhas via API (leitura +
     escrita) num fluxo assistido por IA, em infra própria, só contas próprias/geridas.
   - **Design doc** (obrigatório): use o [`google-ads-api-design-doc.rtf`](google-ads-api-design-doc.rtf) desta pasta como modelo.
   - Quem terá acesso: **Internal users - employees only**.
   - Usa token com ferramenta de terceiros: **No**. App Conversion/Remarketing: **No**.
   - Tipos de campanha: `Search`. Capacidades: **Campaign Creation, Campaign Management, Reporting**.
5. Aprovação costuma sair em ~1 dia útil. **Até lá, leitura funciona; escrita não.**

> **Níveis de acesso, resumo:** Test = só contas de teste · **Analytics = lê
> produção, não escreve** · **Basic = lê + escreve produção** (15k ops/dia) · Standard = mais.

## 4. Projeto no Google Cloud + OAuth
O developer token identifica o app na API; o **OAuth** identifica *quem* autoriza.
São coisas separadas — o OAuth mora no Google Cloud.

1. https://console.cloud.google.com → **crie um projeto** (ex.: `Hermes AutoNext`).
2. **Habilite a Google Ads API:** busque "Google Ads API" no topo → **Ativar**.
   *(ou APIs e serviços → Biblioteca → "Google Ads API" → Ativar.)*
3. **Tela de consentimento (OAuth / Google Auth Platform):**
   - **Branding:** nome do app (ex.: `Vibestack Ads Manager`) + e-mail de suporte.
   - **Público-alvo:** tipo **External** e **PUBLIQUE ("Em produção")**.
     > ⚠️ Se ficar em "Testing", o refresh token **expira em 7 dias**. Publicado,
     > não expira. A scope do Google Ads é "restrita": ao autorizar você verá
     > *"O Google não verificou este app"* → **Avançado → Acessar o app** (ok até 100 usuários, sem verificação formal).
4. **Cliente OAuth:** **Clientes → Criar cliente → tipo "App para computador"
   (Desktop app)** → **Criar**. Copie:
   - `GOOGLE_ADS_CLIENT_ID` (termina em `.apps.googleusercontent.com`)
   - `GOOGLE_ADS_CLIENT_SECRET` (começa com `GOCSPX-`) — pegue em **Baixar o JSON**
     ou abrindo o cliente na aba **Clientes**.

## 5. Gerar o refresh token
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

## 6. Preencher o `.env`
```bash
GOOGLE_ADS_DEVELOPER_TOKEN=<token da MCC (Basic access)>
GOOGLE_ADS_CLIENT_ID=<...apps.googleusercontent.com>
GOOGLE_ADS_CLIENT_SECRET=<GOCSPX-...>
GOOGLE_ADS_REFRESH_TOKEN=<gerado no passo 5>
GOOGLE_ADS_LOGIN_CUSTOMER_ID=<ID da MCC, sem hifens>
GOOGLE_ADS_CUSTOMER_ID=<ID da conta real, sem hifens>
```
Recrie o container pra propagar:
```bash
docker compose up -d openclaw-vibestack
```

## 7. Testar
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

## Erros comuns
| Erro | Causa | Correção |
|---|---|---|
| `DEVELOPER_TOKEN_NOT_APPROVED` | token em Analytics/Test | esperar o **Basic access** (passo 3) |
| Conexão cai após ~7 dias / `invalid_grant` | consent screen em "Testing" | **publicar** o app e refazer o refresh token (passo 4) |
| `USER_PERMISSION_DENIED` | `login_customer_id` errado, conta não vinculada, ou autorizou com o Google errado | MCC certa (sem hífens); vincular a conta na MCC; autorizar com o Google que acessa o Ads |

## Referências
- MCP: `middleware/google_ads_cli_mcp.py` · CLI: `middleware/googleads_cli.py`
- GAQL: https://developers.google.com/google-ads/api/docs/query/overview
- SDK: https://pypi.org/project/google-ads/
