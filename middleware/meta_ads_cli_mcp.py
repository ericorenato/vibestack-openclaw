#!/usr/bin/env python3
"""MCP server stdio que expõe a Meta Ads CLI oficial (`meta`) como tools tipados.

Cobertura: 11 grupos da CLI (adaccount, campaign, adset, ad, creative,
catalog, page, dataset, insights, product-set, product-item, product-feed),
mais conveniências de pause/resume/archive.

Auth: a CLI lê ACCESS_TOKEN e AD_ACCOUNT_ID do env. Subprocessos herdam
do env do container openclaw-gateway.

Deletes sempre passam --force (MCP não tem prompt interativo).

Formato de saída: cada tool aceita `output_format` (default 'json'). Quando o
JSON da CLI vem quebrado/incompatível, passe 'table', 'csv', 'yaml', 'text'
(o que a CLI suportar) e o wrapper devolve a string crua sem tentar parsear.
Use 'none' para omitir a flag e deixar o default da CLI.

Pacote oficial: https://pypi.org/project/meta-ads/  (v1.0.1, Meta).
"""
import json
import subprocess
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("meta-ads-cli")
CLI = "meta"


def _run(*args: str, output_format: str = "json") -> Any:
    """Executa `meta ads <args>`. Formato de saída configurável.

    output_format:
      - 'json' (default): adiciona --output json e parseia o stdout.
        Em falha de parse, devolve dict com 'raw', 'parse_error' e 'hint'.
      - 'table' | 'csv' | 'yaml' | 'text' | ...: passa direto pra CLI e devolve
        o stdout cru (string), sem parsing. Use quando o JSON estiver quebrado.
      - 'none' ou '': omite --output (usa default da CLI).
    """
    cmd = [CLI, "ads", *args]
    if output_format and output_format != "none":
        cmd += ["--output", output_format]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return {
            "error": r.stderr.strip() or f"exit {r.returncode}",
            "stdout": r.stdout,
            "cmd": " ".join(cmd),
        }
    if output_format == "json":
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError as e:
            return {
                "raw": r.stdout,
                "parse_error": f"JSON inválido: {e.msg} (linha {e.lineno}, col {e.colno})",
                "hint": "Tente output_format='table' ou 'text' pra pular o parsing.",
            }
    return r.stdout


def _flags(**kwargs: Any) -> list[str]:
    """Converte kwargs em lista de flags `--key value`, omitindo None.

    - Booleans True -> flag presente sem valor; False/None -> omite.
    - Listas -> flag repetida pra cada item.
    - Substitui underscore por hífen no nome da flag.
    """
    out: list[str] = []
    for k, v in kwargs.items():
        if v is None:
            continue
        flag = "--" + k.replace("_", "-")
        if isinstance(v, bool):
            if v:
                out.append(flag)
        elif isinstance(v, list):
            for item in v:
                out.extend([flag, str(item)])
        else:
            out.extend([flag, str(v)])
    return out


# ============================================================
# Ad Accounts
# ============================================================

@mcp.tool()
def list_ad_accounts(output_format: str = "json") -> Any:
    """Lista todas as ad accounts acessíveis pelo ACCESS_TOKEN."""
    return _run("adaccount", "list", output_format=output_format)


@mcp.tool()
def get_ad_account(ad_account_id: str, output_format: str = "json") -> Any:
    """Detalhes de uma ad account. Formato: 'act_123456789'."""
    return _run("adaccount", "get", ad_account_id, output_format=output_format)


@mcp.tool()
def current_ad_account(output_format: str = "json") -> Any:
    """Ad account ativa (definida em AD_ACCOUNT_ID env)."""
    return _run("adaccount", "current", output_format=output_format)


# ============================================================
# Campaigns
# ============================================================

@mcp.tool()
def list_campaigns(output_format: str = "json") -> Any:
    """Lista campanhas da ad account ativa."""
    return _run("campaign", "list", output_format=output_format)


@mcp.tool()
def get_campaign(campaign_id: str, output_format: str = "json") -> Any:
    """Detalhes de uma campanha."""
    return _run("campaign", "get", campaign_id, output_format=output_format)


@mcp.tool()
def create_campaign(
    name: str,
    objective: str,
    daily_budget_cents: int | None = None,
    lifetime_budget_cents: int | None = None,
    status: str = "paused",
    adset_budget_sharing: bool = False,
    output_format: str = "json",
) -> Any:
    """Cria uma campanha. Default: PAUSED (para não gastar acidentalmente).

    objective: outcome_sales | outcome_traffic | outcome_leads |
               outcome_awareness | outcome_engagement | outcome_app_promotion.
    budgets em centavos. Use lifetime_budget OU daily_budget, não os dois.
    Para CBO (Campaign Budget Optimization), defina budget aqui e omita no ad set.
    """
    return _run(
        "campaign", "create",
        *_flags(
            name=name,
            objective=objective,
            daily_budget=daily_budget_cents,
            lifetime_budget=lifetime_budget_cents,
            status=status,
            adset_budget_sharing=adset_budget_sharing,
        ),
        output_format=output_format,
    )


@mcp.tool()
def update_campaign(
    campaign_id: str,
    name: str | None = None,
    status: str | None = None,
    daily_budget_cents: int | None = None,
    lifetime_budget_cents: int | None = None,
    output_format: str = "json",
) -> Any:
    """Atualiza campanha. status: active | paused | archived."""
    return _run(
        "campaign", "update", campaign_id,
        *_flags(
            name=name,
            status=status,
            daily_budget=daily_budget_cents,
            lifetime_budget=lifetime_budget_cents,
        ),
        output_format=output_format,
    )


@mcp.tool()
def pause_campaign(campaign_id: str, output_format: str = "json") -> Any:
    """Pausa campanha (status -> paused). Atalho pra update_campaign."""
    return _run("campaign", "update", campaign_id, "--status", "paused", output_format=output_format)


@mcp.tool()
def resume_campaign(campaign_id: str, output_format: str = "json") -> Any:
    """Reativa campanha (status -> active). Atalho pra update_campaign."""
    return _run("campaign", "update", campaign_id, "--status", "active", output_format=output_format)


@mcp.tool()
def archive_campaign(campaign_id: str, output_format: str = "json") -> Any:
    """Arquiva campanha (status -> archived)."""
    return _run("campaign", "update", campaign_id, "--status", "archived", output_format=output_format)


@mcp.tool()
def delete_campaign(campaign_id: str, output_format: str = "json") -> Any:
    """Deleta campanha (e todos ad sets/ads filhos). DESTRUTIVO. Sempre --force."""
    return _run("campaign", "delete", campaign_id, "--force", output_format=output_format)


# ============================================================
# Ad Sets
# ============================================================

@mcp.tool()
def list_ad_sets(campaign_id: str | None = None, output_format: str = "json") -> Any:
    """Lista ad sets. Se campaign_id informado, filtra por campanha."""
    args = ["adset", "list"]
    if campaign_id:
        args.append(campaign_id)
    return _run(*args, output_format=output_format)


@mcp.tool()
def get_ad_set(ad_set_id: str, output_format: str = "json") -> Any:
    """Detalhes de um ad set."""
    return _run("adset", "get", ad_set_id, output_format=output_format)


@mcp.tool()
def create_ad_set(
    campaign_id: str,
    name: str,
    optimization_goal: str,
    billing_event: str,
    daily_budget_cents: int | None = None,
    lifetime_budget_cents: int | None = None,
    bid_amount_cents: int | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    status: str = "paused",
    targeting_countries: list[str] | None = None,
    pixel_id: str | None = None,
    custom_event_type: str | None = None,
    output_format: str = "json",
) -> Any:
    """Cria ad set numa campanha. Default: PAUSED.

    optimization_goal: link_clicks | impressions | reach | offsite_conversions |
                       landing_page_views | thruplay | value | post_engagement |
                       page_likes | lead_generation | app_installs | event_responses |
                       conversations.
    billing_event: impressions | link_clicks | clicks | thruplay | app_installs |
                   page_likes | post_engagement.
    targeting_countries: lista de códigos ISO ['US', 'BR', 'CA']. Convertido pra CSV.
    Para conversão (campaign OUTCOME_SALES): defina pixel_id + custom_event_type
    (ex: 'purchase'). Omita budgets se a campanha usa CBO.
    lifetime_budget exige end_time.
    """
    countries = ",".join(targeting_countries) if targeting_countries else None
    return _run(
        "adset", "create", campaign_id,
        *_flags(
            name=name,
            optimization_goal=optimization_goal,
            billing_event=billing_event,
            daily_budget=daily_budget_cents,
            lifetime_budget=lifetime_budget_cents,
            bid_amount=bid_amount_cents,
            start_time=start_time,
            end_time=end_time,
            status=status,
            targeting_countries=countries,
            pixel_id=pixel_id,
            custom_event_type=custom_event_type,
        ),
        output_format=output_format,
    )


@mcp.tool()
def update_ad_set(
    ad_set_id: str,
    name: str | None = None,
    status: str | None = None,
    daily_budget_cents: int | None = None,
    lifetime_budget_cents: int | None = None,
    bid_amount_cents: int | None = None,
    end_time: str | None = None,
    output_format: str = "json",
) -> Any:
    """Atualiza ad set. status: active | paused | archived."""
    return _run(
        "adset", "update", ad_set_id,
        *_flags(
            name=name,
            status=status,
            daily_budget=daily_budget_cents,
            lifetime_budget=lifetime_budget_cents,
            bid_amount=bid_amount_cents,
            end_time=end_time,
        ),
        output_format=output_format,
    )


@mcp.tool()
def pause_ad_set(ad_set_id: str, output_format: str = "json") -> Any:
    """Pausa ad set."""
    return _run("adset", "update", ad_set_id, "--status", "paused", output_format=output_format)


@mcp.tool()
def resume_ad_set(ad_set_id: str, output_format: str = "json") -> Any:
    """Reativa ad set."""
    return _run("adset", "update", ad_set_id, "--status", "active", output_format=output_format)


@mcp.tool()
def delete_ad_set(ad_set_id: str, output_format: str = "json") -> Any:
    """Deleta ad set (e ads filhos). DESTRUTIVO. Sempre --force."""
    return _run("adset", "delete", ad_set_id, "--force", output_format=output_format)


# ============================================================
# Ads
# ============================================================

@mcp.tool()
def list_ads(ad_set_id: str | None = None, output_format: str = "json") -> Any:
    """Lista ads. Se ad_set_id informado, filtra por ad set."""
    args = ["ad", "list"]
    if ad_set_id:
        args.append(ad_set_id)
    return _run(*args, output_format=output_format)


@mcp.tool()
def get_ad(ad_id: str, output_format: str = "json") -> Any:
    """Detalhes de um ad."""
    return _run("ad", "get", ad_id, output_format=output_format)


@mcp.tool()
def create_ad(
    ad_set_id: str,
    name: str,
    creative_id: str,
    status: str = "paused",
    pixel_id: str | None = None,
    tracking_specs: str | None = None,
    output_format: str = "json",
) -> Any:
    """Cria ad num ad set, referenciando um creative existente. Default: PAUSED.

    Antes de chamar: crie o creative com create_creative e use o ID retornado.
    Para conversão, use pixel_id (auto-gera tracking specs). tracking_specs aceita
    JSON cru pra config customizada (não use junto com pixel_id).
    """
    return _run(
        "ad", "create", ad_set_id,
        *_flags(
            name=name,
            creative_id=creative_id,
            status=status,
            pixel_id=pixel_id,
            tracking_specs=tracking_specs,
        ),
        output_format=output_format,
    )


@mcp.tool()
def update_ad(
    ad_id: str,
    name: str | None = None,
    creative_id: str | None = None,
    status: str | None = None,
    output_format: str = "json",
) -> Any:
    """Atualiza ad. status: active | paused | archived."""
    return _run(
        "ad", "update", ad_id,
        *_flags(name=name, creative_id=creative_id, status=status),
        output_format=output_format,
    )


@mcp.tool()
def pause_ad(ad_id: str, output_format: str = "json") -> Any:
    """Pausa ad."""
    return _run("ad", "update", ad_id, "--status", "paused", output_format=output_format)


@mcp.tool()
def resume_ad(ad_id: str, output_format: str = "json") -> Any:
    """Reativa ad."""
    return _run("ad", "update", ad_id, "--status", "active", output_format=output_format)


@mcp.tool()
def delete_ad(ad_id: str, output_format: str = "json") -> Any:
    """Deleta ad. DESTRUTIVO. Sempre --force."""
    return _run("ad", "delete", ad_id, "--force", output_format=output_format)


# ============================================================
# Creatives
# ============================================================

@mcp.tool()
def list_creatives(output_format: str = "json") -> Any:
    """Lista creatives da ad account ativa."""
    return _run("creative", "list", output_format=output_format)


@mcp.tool()
def get_creative(creative_id: str, output_format: str = "json") -> Any:
    """Detalhes de um creative."""
    return _run("creative", "get", creative_id, output_format=output_format)


@mcp.tool()
def create_creative(
    name: str,
    page_id: str,
    image_path: str | None = None,
    video_path: str | None = None,
    body: str | None = None,
    title: str | None = None,
    link_url: str | None = None,
    description: str | None = None,
    call_to_action: str | None = None,
    instagram_actor_id: str | None = None,
    output_format: str = "json",
) -> Any:
    """Cria creative (modo standard — single image OU video).

    page_id é obrigatório (identidade do anúncio).
    Use image_path OU video_path (path dentro do container).
    call_to_action: shop_now | learn_more | sign_up | book_travel | buy_now |
                    contact_us | download | get_offer | get_quote | apply_now |
                    no_button | open_link | subscribe | watch_more.
    Para DCO (múltiplas variantes), use create_creative_dco.
    """
    return _run(
        "creative", "create",
        *_flags(
            name=name,
            page_id=page_id,
            image=image_path,
            video=video_path,
            body=body,
            title=title,
            link_url=link_url,
            description=description,
            call_to_action=call_to_action,
            instagram_actor_id=instagram_actor_id,
        ),
        output_format=output_format,
    )


@mcp.tool()
def create_creative_dco(
    name: str,
    page_id: str,
    link_url: str,
    image_paths: list[str] | None = None,
    video_paths: list[str] | None = None,
    titles: list[str] | None = None,
    bodies: list[str] | None = None,
    descriptions: list[str] | None = None,
    call_to_actions: list[str] | None = None,
    instagram_actor_id: str | None = None,
    output_format: str = "json",
) -> Any:
    """Cria creative DCO (Dynamic Creative Optimization).

    Meta testa combinações automaticamente. Limites:
    10 images/videos, 5 titles, 5 bodies, 5 descriptions, 5 call_to_actions.
    """
    return _run(
        "creative", "create",
        *_flags(
            name=name,
            page_id=page_id,
            link_url=link_url,
            images=image_paths,
            videos=video_paths,
            titles=titles,
            bodies=bodies,
            descriptions=descriptions,
            call_to_actions=call_to_actions,
            instagram_actor_id=instagram_actor_id,
        ),
        output_format=output_format,
    )


@mcp.tool()
def update_creative(
    creative_id: str,
    name: str | None = None,
    image_path: str | None = None,
    video_path: str | None = None,
    body: str | None = None,
    title: str | None = None,
    link_url: str | None = None,
    description: str | None = None,
    call_to_action: str | None = None,
    instagram_actor_id: str | None = None,
    status: str | None = None,
    output_format: str = "json",
) -> Any:
    """Atualiza creative. Apenas campos informados são alterados.

    Meta restringe alguns campos pós-criação — pode ser necessário
    criar novo creative em vez de editar.
    """
    return _run(
        "creative", "update", creative_id,
        *_flags(
            name=name,
            image=image_path,
            video=video_path,
            body=body,
            title=title,
            link_url=link_url,
            description=description,
            call_to_action=call_to_action,
            instagram_actor_id=instagram_actor_id,
            status=status,
        ),
        output_format=output_format,
    )


@mcp.tool()
def delete_creative(creative_id: str, output_format: str = "json") -> Any:
    """Deleta creative. Bloqueia se está em uso por ads ativos. Sempre --force."""
    return _run("creative", "delete", creative_id, "--force", output_format=output_format)


# ============================================================
# Insights (métricas de performance)
# ============================================================

@mcp.tool()
def get_insights(
    date_preset: str | None = None,
    since: str | None = None,
    until: str | None = None,
    time_increment: str = "all_days",
    breakdown: list[str] | None = None,
    fields: list[str] | None = None,
    campaign_id: str | None = None,
    adset_id: str | None = None,
    ad_id: str | None = None,
    sort: str | None = None,
    limit: int = 50,
    output_format: str = "json",
) -> Any:
    """Query de performance: impressões, cliques, gasto, CPC, CPM, etc.

    date_preset: today | yesterday | last_3d | last_7d | last_14d | last_30d (default) |
                 last_90d | this_month | last_month. Sobrescreve since/until.
    since/until: YYYY-MM-DD. Sobrescrevem date_preset.
    time_increment: daily | weekly | monthly | all_days (default).
    breakdown: age | gender | country | publisher_platform | device_platform |
               platform_position | impression_device. Pode repetir.
    fields: lista de métricas. Default: spend,impressions,clicks,ctr,cpc,reach.
    Filtros: campaign_id, adset_id, ad_id (escolha um nível).
    sort: ex 'spend_descending'.
    """
    args = ["insights", "get"]
    args += _flags(
        date_preset=date_preset,
        since=since,
        until=until,
        time_increment=time_increment,
        campaign_id=campaign_id,
        adset_id=adset_id,
        ad_id=ad_id,
        sort=sort,
        limit=limit,
    )
    for b in (breakdown or []):
        args += ["--breakdown", b]
    if fields:
        args += ["--fields", ",".join(fields)]
    return _run(*args, output_format=output_format)


# ============================================================
# Catalogs
# ============================================================

@mcp.tool()
def list_catalogs(output_format: str = "json") -> Any:
    """Lista product catalogs do business."""
    return _run("catalog", "list", output_format=output_format)


@mcp.tool()
def get_catalog(catalog_id: str, output_format: str = "json") -> Any:
    """Detalhes de um catálogo."""
    return _run("catalog", "get", catalog_id, output_format=output_format)


@mcp.tool()
def create_catalog(name: str, vertical: str = "commerce", output_format: str = "json") -> Any:
    """Cria catálogo. vertical: commerce (default) | hotels | flights | destinations |
    home_listings | vehicles | adoptable_pets | offer_items | offline_commerce |
    transactable_items | generic | local_service_businesses."""
    return _run("catalog", "create", *_flags(name=name, vertical=vertical), output_format=output_format)


@mcp.tool()
def update_catalog(catalog_id: str, name: str | None = None, output_format: str = "json") -> Any:
    """Atualiza catálogo."""
    return _run("catalog", "update", catalog_id, *_flags(name=name), output_format=output_format)


@mcp.tool()
def delete_catalog(catalog_id: str, output_format: str = "json") -> Any:
    """Deleta catálogo. Bloqueia se houver feeds/ads ativos. Sempre --force."""
    return _run("catalog", "delete", catalog_id, "--force", output_format=output_format)


# ============================================================
# Pages
# ============================================================

@mcp.tool()
def list_pages(output_format: str = "json") -> Any:
    """Lista business pages acessíveis."""
    return _run("page", "list", output_format=output_format)


@mcp.tool()
def get_page(page_id: str, output_format: str = "json") -> Any:
    """Detalhes de uma Facebook Page."""
    return _run("page", "get", page_id, output_format=output_format)


# ============================================================
# Datasets (Pixels)
# ============================================================

@mcp.tool()
def list_datasets(output_format: str = "json") -> Any:
    """Lista datasets (ads pixels) do business."""
    return _run("dataset", "list", output_format=output_format)


@mcp.tool()
def get_dataset(pixel_id: str, output_format: str = "json") -> Any:
    """Detalhes de um dataset (pixel)."""
    return _run("dataset", "get", pixel_id, output_format=output_format)


@mcp.tool()
def create_dataset(name: str, output_format: str = "json") -> Any:
    """Cria dataset (pixel) no business. Usuário autenticado fica com
    ADVERTISE/ANALYZE/EDIT automaticamente."""
    return _run("dataset", "create", *_flags(name=name), output_format=output_format)


@mcp.tool()
def connect_dataset(
    pixel_id: str,
    ad_account_id: str | None = None,
    catalog_id: str | None = None,
    output_format: str = "json",
) -> Any:
    """Conecta dataset a uma ad account e/ou catálogo (informe pelo menos um)."""
    return _run(
        "dataset", "connect", pixel_id,
        *_flags(ad_account_id=ad_account_id, catalog_id=catalog_id),
        output_format=output_format,
    )


@mcp.tool()
def disconnect_dataset(pixel_id: str, ad_account_id: str, output_format: str = "json") -> Any:
    """Desconecta dataset de uma ad account."""
    return _run(
        "dataset", "disconnect", pixel_id,
        *_flags(ad_account_id=ad_account_id),
        output_format=output_format,
    )


@mcp.tool()
def assign_user_to_dataset(
    pixel_id: str,
    user_id: str | None = None,
    tasks: list[str] | None = None,
    output_format: str = "json",
) -> Any:
    """Atribui usuário ao dataset. user_id default = usuário autenticado.
    tasks: advertise | analyze | edit | upload. Default: [advertise, analyze]."""
    return _run(
        "dataset", "assign-user", pixel_id,
        *_flags(user_id=user_id, tasks=tasks),
        output_format=output_format,
    )


# ============================================================
# Product Sets
# ============================================================

@mcp.tool()
def list_product_sets(catalog_id: str, output_format: str = "json") -> Any:
    """Lista product sets de um catálogo."""
    return _run("product-set", "list", *_flags(catalog_id=catalog_id), output_format=output_format)


@mcp.tool()
def get_product_set(product_set_id: str, output_format: str = "json") -> Any:
    """Detalhes de um product set."""
    return _run("product-set", "get", product_set_id, output_format=output_format)


@mcp.tool()
def create_product_set(
    catalog_id: str,
    name: str,
    filter_json: str | None = None,
    retailer_id: str | None = None,
    output_format: str = "json",
) -> Any:
    """Cria product set dentro de um catálogo.

    filter_json: expressão JSON (ex: '{"availability":{"eq":"in stock"}}').
    """
    return _run(
        "product-set", "create",
        *_flags(catalog_id=catalog_id, name=name, filter=filter_json, retailer_id=retailer_id),
        output_format=output_format,
    )


@mcp.tool()
def update_product_set(
    product_set_id: str,
    name: str | None = None,
    filter_json: str | None = None,
    retailer_id: str | None = None,
    output_format: str = "json",
) -> Any:
    """Atualiza product set."""
    return _run(
        "product-set", "update", product_set_id,
        *_flags(name=name, filter=filter_json, retailer_id=retailer_id),
        output_format=output_format,
    )


@mcp.tool()
def delete_product_set(product_set_id: str, output_format: str = "json") -> Any:
    """Deleta product set. Sempre --force."""
    return _run("product-set", "delete", product_set_id, "--force", output_format=output_format)


# ============================================================
# Product Items
# ============================================================

@mcp.tool()
def list_product_items(catalog_id: str, output_format: str = "json") -> Any:
    """Lista product items de um catálogo."""
    return _run("product-item", "list", *_flags(catalog_id=catalog_id), output_format=output_format)


@mcp.tool()
def get_product_item(product_item_id: str, output_format: str = "json") -> Any:
    """Detalhes de um product item."""
    return _run("product-item", "get", product_item_id, output_format=output_format)


@mcp.tool()
def create_product_item(
    catalog_id: str,
    retailer_id: str,
    name: str,
    url: str,
    image_url: str,
    price_cents: int,
    currency: str,
    description: str | None = None,
    brand: str | None = None,
    category: str | None = None,
    availability: str = "in stock",
    condition: str = "new",
    output_format: str = "json",
) -> Any:
    """Cria product item num catálogo.

    price_cents: em centavos (999 = $9.99).
    currency: ISO 4217 ('USD', 'BRL', etc.).
    availability: in stock | out of stock | preorder | available for order |
                  discontinued | pending | mark_as_sold.
    condition: new | refurbished | used | used_like_new | used_good | used_fair |
               cpo | open_box_new.
    """
    return _run(
        "product-item", "create",
        *_flags(
            catalog_id=catalog_id,
            retailer_id=retailer_id,
            name=name,
            url=url,
            image_url=image_url,
            price=price_cents,
            currency=currency,
            description=description,
            brand=brand,
            category=category,
            availability=availability,
            condition=condition,
        ),
        output_format=output_format,
    )


@mcp.tool()
def update_product_item(
    product_item_id: str,
    name: str | None = None,
    description: str | None = None,
    url: str | None = None,
    image_url: str | None = None,
    brand: str | None = None,
    category: str | None = None,
    availability: str | None = None,
    condition: str | None = None,
    price_cents: int | None = None,
    currency: str | None = None,
    output_format: str = "json",
) -> Any:
    """Atualiza product item."""
    return _run(
        "product-item", "update", product_item_id,
        *_flags(
            name=name,
            description=description,
            url=url,
            image_url=image_url,
            brand=brand,
            category=category,
            availability=availability,
            condition=condition,
            price=price_cents,
            currency=currency,
        ),
        output_format=output_format,
    )


@mcp.tool()
def delete_product_item(product_item_id: str, output_format: str = "json") -> Any:
    """Deleta product item. Sempre --force."""
    return _run("product-item", "delete", product_item_id, "--force", output_format=output_format)


# ============================================================
# Product Feeds
# ============================================================

@mcp.tool()
def list_product_feeds(catalog_id: str, output_format: str = "json") -> Any:
    """Lista product feeds de um catálogo."""
    return _run("product-feed", "list", *_flags(catalog_id=catalog_id), output_format=output_format)


@mcp.tool()
def get_product_feed(product_feed_id: str, output_format: str = "json") -> Any:
    """Detalhes de um product feed."""
    return _run("product-feed", "get", product_feed_id, output_format=output_format)


@mcp.tool()
def create_product_feed(
    catalog_id: str,
    name: str,
    feed_type: str = "products",
    default_currency: str | None = None,
    country: str | None = None,
    encoding: str | None = None,
    file_name: str | None = None,
    output_format: str = "json",
) -> Any:
    """Cria product feed num catálogo.

    feed_type: products (default) | automotive_model | destination | flight |
               home_listing | hotel | hotel_room | local_inventory | media_title |
               offer | transactable_items | vehicles | vehicle_offer.
    encoding: autodetect | utf8 | latin1 | utf16be | utf16le | utf32be | utf32le.
    """
    return _run(
        "product-feed", "create",
        *_flags(
            catalog_id=catalog_id,
            name=name,
            feed_type=feed_type,
            default_currency=default_currency,
            country=country,
            encoding=encoding,
            file_name=file_name,
        ),
        output_format=output_format,
    )


@mcp.tool()
def update_product_feed(
    product_feed_id: str,
    name: str | None = None,
    default_currency: str | None = None,
    country: str | None = None,
    encoding: str | None = None,
    file_name: str | None = None,
    output_format: str = "json",
) -> Any:
    """Atualiza product feed."""
    return _run(
        "product-feed", "update", product_feed_id,
        *_flags(
            name=name,
            default_currency=default_currency,
            country=country,
            encoding=encoding,
            file_name=file_name,
        ),
        output_format=output_format,
    )


@mcp.tool()
def delete_product_feed(product_feed_id: str, output_format: str = "json") -> Any:
    """Deleta product feed. Sempre --force."""
    return _run("product-feed", "delete", product_feed_id, "--force", output_format=output_format)


if __name__ == "__main__":
    mcp.run()
