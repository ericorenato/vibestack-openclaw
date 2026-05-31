# agency/ — prompts dos agentes (templates)

Esta pasta traz os **prompts prontos** dos 6 agentes da agência de tráfego, para você carregar no **OpenClaw** (ou no **Hermes**). São **templates**: tudo que depende do seu contexto está marcado com **placeholders `{{ASSIM}}`** — troque-os antes de usar.

> ⚠️ **Este `README.md` é um guia, não um prompt.** Não cole o conteúdo dele em nenhum agente. Carregue só os arquivos `IDENTITY.md` / `SOUL.md` / `USER.md` / `TOOLS.md` / `AGENTS.md`.

## Como usar (resumo)

1. **Copie** a pasta `agency/` para o seu projeto (ou edite aqui mesmo no seu fork).
2. **Substitua todos os `{{...}}`** pelos seus valores (veja a tabela abaixo). Dica: um "localizar e substituir" no editor resolve rápido; confira que não sobrou nenhum `{{` com:
   ```
   grep -rn "{{" agency/
   ```
3. **Crie os agentes** no OpenClaw e cole cada arquivo no campo correspondente (veja "Os 5 arquivos por agente").
4. Para que um agente acione outro (ex.: Diretor → Analista), habilite **subagentes** no OpenClaw — veja o `README.md` da raiz, seção *"Passo 13 — Habilitar subagentes"*.

## Os 5 arquivos por agente

Cada pasta de agente tem até 5 arquivos (a CLI do OpenClaw os usa como blocos do prompt do agente; no Hermes, concatene-os no system prompt):

| Arquivo       | O que é                                                                 |
|---------------|-------------------------------------------------------------------------|
| `IDENTITY.md` | Nome, "vibe" e emoji do agente — quem ele é em uma linha.               |
| `SOUL.md`     | Personalidade e princípios — como ele pensa e fala.                    |
| `USER.md`     | Com quem ele fala (seus interlocutores) e em que tom/idioma.            |
| `TOOLS.md`    | Quais tools MCP ele pode usar e as regras de uso (só alguns agentes).  |
| `AGENTS.md`   | O papel operacional: fluxo, alçada, o que faz e o que **não** faz.     |

## Os 6 agentes e o fluxo

- **Diretor** 🎯 — porta única com você (o humano). Recebe tudo pelo seu canal, roteia e devolve. Não executa nada no Meta.
- **Analista** 📊 — só leitura de Meta Ads; entrega números + leitura, sem opinar.
- **Estrategista** ♟️ — decide a ação (ancorada em número). Tem alçada própria; acima dela, escala pro Diretor (= pede sua aprovação).
- **Copywriter** ✍️ — escreve as variações de texto do anúncio.
- **Criativo** 🎬 — produz a mídia (imagem/vídeo) via `media-editor` + `higgsfield`/`atlascloud`.
- **Gestor de Tráfego** 🛠️ — **único** que escreve no Meta Ads; executa só sob ordem da Estrategista (autônoma) ou do Diretor (aprovada por você).

```
Você → Diretor → Analista → Estrategista ─┬─ (na alçada) → Gestor → Meta Ads
                                          └─ (acima)     → Diretor → você aprova → Gestor
                              Estrategista → Copywriter / Criativo (quando há peça nova)
```

## Placeholders — troque todos

| Placeholder              | O que colocar                                                                 | Onde aparece |
|--------------------------|-------------------------------------------------------------------------------|--------------|
| `{{DONO}}`               | Nome do humano dono/decisor (quem aprova as ações).                           | Diretor, Estrategista, Gestor, Copywriter |
| `{{DONO_EMAIL}}`         | E-mail desse dono (identificação no sistema).                                 | Diretor |
| `{{CANAL}}`              | Canal por onde o dono fala com o Diretor — ex.: `WhatsApp` ou `Telegram`.     | Diretor |
| `{{PRODUTO_1}}`          | Nome do seu 1º produto/oferta.                                                | Copywriter |
| `{{TOM_PRODUTO_1}}`      | Tom de voz desse produto (ex.: "utilitário, direto, ganho concreto").         | Copywriter |
| `{{PRODUTO_2}}`          | Nome do seu 2º produto (apague se só tiver um).                               | Copywriter |
| `{{TOM_PRODUTO_2}}`      | Tom de voz do 2º produto.                                                     | Copywriter |
| `{{ALCADA_BUDGET_PCT}}`  | % de ajuste de budget que a Estrategista pode fazer **sem** te perguntar (ex.: `30`). | Estrategista |
| `{{ALCADA_GASTO_DIA}}`   | Teto de gasto incremental/dia que dispensa sua aprovação (ex.: `R$ 200/dia`). | Estrategista |
| `{{PESSOA_DA_MARCA}}`    | (Opcional) Quem é o rosto fixo dos criativos — dono, porta-voz, modelo.       | Criativo |
| `{{SLUG_DA_PESSOA}}`     | (Opcional) Apelido em minúsculas/sem espaço pra nomear a seed e o soul-id (ex.: `rosto-marca`). | Criativo |

> O `{{PESSOA_DA_MARCA}}` / `{{SLUG_DA_PESSOA}}` só importam se você for gerar criativos sempre com **um rosto fixo** (via soul-id do Higgsfield). Se não for, apague essa seção do `criativo/AGENTS.md`.

## Notas

- **Renomear agentes/papéis** é livre — mas se mudar um nome (ex.: "Gestor"), troque também as menções a ele nos outros arquivos.
- Os caminhos e nomes de tools (`/root/.openclaw/workspace/...`, `create_creative`, `finalize_for_meta`, etc.) **não** são placeholders: são reais do projeto, deixe como estão.
- Estes prompts são afinados para o conjunto de MCP servers do projeto (`meta-ads`, `media-editor`, `whatsapp`, `higgsfield`, `atlascloud`) — veja o `README.md` da raiz.
