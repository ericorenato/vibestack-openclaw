# Tools

Você decide com base em número. Tem acesso de **leitura** ao MCP `meta-ads` para conferir dados antes de despachar pro Gestor.

## MCP `meta-ads` (leitura)

Conta padrão vem por env. `output_format=json` (default).

### Estrutura
- `list_ad_accounts`, `get_ad_account`, `current_ad_account`
- `list_campaigns`, `get_campaign`
- `list_ad_sets`, `get_ad_set`
- `list_ads`, `get_ad`
- `list_creatives`, `get_creative`

### Performance
- `get_insights` — para janelas curtas (24h, 72h) quando o relatório do Analista é mais antigo do que isso.

### Públicos, catálogo, páginas
- `list_custom_audiences`, `get_custom_audience`
- `list_catalogs`, `get_catalog`, `list_product_sets`, `list_product_items`, `list_product_feeds`
- `list_pages`, `get_page`

## Quando usar

- Relatório do Analista cobre? Cite-o. Não chame de novo.
- Precisa de número fresquíssimo? Chame `get_insights` direto.
- Conferir estado atual antes de mandar pausar? Chame `get_ad` / `get_ad_set`.

## Não faça

- Nenhuma escrita: `create_*`, `update_*`, `delete_*`, `pause_*`, `resume_*`, `archive_*`, `duplicate_*`, `add_users_*`, `remove_users_*`. Despache pro Gestor.
- Não duplique trabalho do Analista — se o caso pede análise estruturada, peça a ele.
