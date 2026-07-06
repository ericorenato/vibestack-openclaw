#!/usr/bin/env python3
"""MCP server stdio que expõe o Google Ads como tools tipados (read + write).

Diferente do meta_ads_cli_mcp.py (que envelopa a CLI oficial `meta` via
subprocess), o Google Ads NÃO tem CLI oficial equivalente. Aqui falamos direto
com a API pela biblioteca cliente OFICIAL `google-ads` (PyPI):
  - Leitura  -> GAQL via GoogleAdsService.search
  - Escrita  -> mutate_* dos services por entidade

Auth: GoogleAdsClient.load_from_env() lê as GOOGLE_ADS_* do ambiente
(DEVELOPER_TOKEN, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, LOGIN_CUSTOMER_ID,
USE_PROTO_PLUS). O entrypoint repassa essas vars ao spawnar o MCP child.
A conta operada (customer_id) NÃO faz parte da config do client — é por
request; usamos GOOGLE_ADS_CUSTOMER_ID como default e toda tool aceita
`customer_id` para a agência operar contas de clientes diferentes.

Convenções (espelham o meta_ads_cli_mcp.py):
  - Nunca levanta exceção: toda tool devolve dict; erro vira {"error": ...}.
  - create_* saem PAUSED por padrão (não gastar acidentalmente).
  - remove_* são DESTRUTIVOS (sem prompt — MCP não tem interativo).

Valores monetários em MICROS (1 unidade da moeda da conta = 1.000.000 micros),
o análogo dos "cents" do meta. As tools de orçamento aceitam `amount_units`
(float, na moeda da conta) por conveniência e convertem para micros.

Pacote oficial: https://pypi.org/project/google-ads/
"""
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("google-ads")

# Importado lazy dentro de _client() para que a falta do pacote/credenciais não
# derrube o processo no import (as tools devolvem erro em vez de crashar).
_CLIENT: Any = None
_CLIENT_ERR: dict[str, str] | None = None


# ============================================================
# Cliente + helpers
# ============================================================

def _client() -> Any:
    """Devolve um GoogleAdsClient (singleton) ou um dict de erro.

    Constrói via load_from_env(): exige GOOGLE_ADS_DEVELOPER_TOKEN, CLIENT_ID,
    CLIENT_SECRET, REFRESH_TOKEN e USE_PROTO_PLUS no ambiente (LOGIN_CUSTOMER_ID
    é opcional, só para contas gerenciadas/MCC). Cacheia o resultado.
    """
    global _CLIENT, _CLIENT_ERR
    if _CLIENT is not None:
        return _CLIENT
    if _CLIENT_ERR is not None:
        return _CLIENT_ERR
    try:
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
    except Exception as e:  # noqa: BLE001
        _CLIENT_ERR = {"error": f"pacote google-ads indisponível no venv: {e}"}
        return _CLIENT_ERR
    # load_from_env exige USE_PROTO_PLUS definido; garantimos um default.
    os.environ.setdefault("GOOGLE_ADS_USE_PROTO_PLUS", "True")
    try:
        _CLIENT = GoogleAdsClient.load_from_env()
    except Exception as e:  # noqa: BLE001
        _CLIENT_ERR = {
            "error": f"falha ao inicializar o Google Ads client: {e}",
            "hint": "Confira GOOGLE_ADS_DEVELOPER_TOKEN/CLIENT_ID/CLIENT_SECRET/"
            "REFRESH_TOKEN no .env. Gere o refresh_token com `google-ads-auth`.",
        }
        return _CLIENT_ERR
    return _CLIENT


def _gerr(exc: Any) -> dict[str, Any]:
    """Converte uma GoogleAdsException em dict (error_code + message por erro)."""
    errors = []
    try:
        for err in exc.failure.errors:
            code = ""
            try:
                # error_code é um oneof; pega o campo setado.
                ec = err.error_code
                for field in type(ec).pb(ec).DESCRIPTOR.fields:
                    val = getattr(ec, field.name)
                    if val:
                        code = f"{field.name}={val}"
                        break
            except Exception:  # noqa: BLE001
                pass
            # field_path: qual campo causou o erro (ex.: operations[0].create.X).
            field_path = ""
            try:
                parts = []
                for el in err.location.field_path_elements:
                    parts.append(el.field_name + (f"[{el.index}]" if el.index else ""))
                field_path = ".".join(parts)
            except Exception:  # noqa: BLE001
                pass
            item = {"error_code": code, "message": err.message}
            if field_path:
                item["field_path"] = field_path
            errors.append(item)
    except Exception:  # noqa: BLE001
        errors.append({"message": str(exc)})
    req_id = getattr(exc, "request_id", None)
    out: dict[str, Any] = {"error": "GoogleAdsException", "errors": errors}
    if req_id:
        out["request_id"] = req_id
    return out


def _resolve_cid(customer_id: str | None = None) -> str | None:
    """Resolve o customer_id (conta operada). Remove hífens (123-456-7890)."""
    cid = customer_id or os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "")
    cid = cid.replace("-", "").strip()
    return cid or None


def _to_micros(amount_units: float | None) -> int | None:
    """Converte um valor na moeda da conta (ex.: 50.0) para micros (50_000_000)."""
    if amount_units is None:
        return None
    return int(round(float(amount_units) * 1_000_000))


def _rows(query: str, customer_id: str | None = None) -> Any:
    """Roda GAQL (GoogleAdsService.search) e devolve lista de dicts (ou erro)."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente", "hint": "defina GOOGLE_ADS_CUSTOMER_ID no .env ou passe customer_id."}
    try:
        from google.protobuf.json_format import MessageToDict  # type: ignore
        service = client.get_service("GoogleAdsService")
        request = client.get_type("SearchGoogleAdsRequest")
        request.customer_id = cid
        request.query = query
        out = []
        for row in service.search(request=request):
            out.append(MessageToDict(row._pb, preserving_proto_field_name=True))
        return out
    except Exception as e:  # noqa: BLE001
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        if isinstance(e, GoogleAdsException):
            return _gerr(e)
        return {"error": str(e), "query": query}


def _mutate(service_name: str, method: str, operations: list, customer_id: str) -> Any:
    """Executa um mutate_* e devolve os resource_names afetados (ou erro)."""
    client = _client()
    if isinstance(client, dict):
        return client
    try:
        service = client.get_service(service_name)
        response = getattr(service, method)(customer_id=customer_id, operations=operations)
        return {"results": [r.resource_name for r in response.results]}
    except Exception as e:  # noqa: BLE001
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        if isinstance(e, GoogleAdsException):
            return _gerr(e)
        return {"error": str(e)}


def _status_update(entity_type: str, service_name: str, mutate_method: str,
                   resource_name: str, status: str, customer_id: str) -> Any:
    """Update genérico do campo `status` (pause/resume/enable) com update_mask."""
    client = _client()
    if isinstance(client, dict):
        return client
    try:
        from google.api_core import protobuf_helpers  # type: ignore
        op = client.get_type(entity_type)
        entity = op.update
        entity.resource_name = resource_name
        entity.status = getattr(client.enums, _STATUS_ENUM[service_name])[status.upper()]
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, entity._pb))
        return _mutate(service_name, mutate_method, [op], customer_id)
    except KeyError:
        return {"error": f"status inválido: {status}"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


# Nome do enum de status por service (usado no _status_update).
_STATUS_ENUM = {
    "CampaignService": "CampaignStatusEnum",
    "AdGroupService": "AdGroupStatusEnum",
    "AdGroupAdService": "AdGroupAdStatusEnum",
    "AdGroupCriterionService": "AdGroupCriterionStatusEnum",
}


# ============================================================
# Contas
# ============================================================

@mcp.tool()
def list_accessible_customers() -> Any:
    """Lista os customer IDs diretamente acessíveis pelo refresh_token.

    Retorna resource_names 'customers/{id}'. Use o id (sem hífen) como
    customer_id nas demais tools, ou defina GOOGLE_ADS_CUSTOMER_ID no .env.
    """
    client = _client()
    if isinstance(client, dict):
        return client
    try:
        service = client.get_service("CustomerService")
        res = service.list_accessible_customers()
        return {"resource_names": list(res.resource_names)}
    except Exception as e:  # noqa: BLE001
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        if isinstance(e, GoogleAdsException):
            return _gerr(e)
        return {"error": str(e)}


@mcp.tool()
def current_customer() -> Any:
    """Conta ativa (lida do env GOOGLE_ADS_CUSTOMER_ID) e a MCC de login."""
    return {
        "customer_id": _resolve_cid(),
        "login_customer_id": os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "") or None,
    }


# ============================================================
# GAQL cru
# ============================================================

@mcp.tool()
def gaql_search(query: str, customer_id: str | None = None) -> Any:
    """Executa uma query GAQL arbitrária na conta e devolve as linhas.

    Ex.: "SELECT campaign.id, campaign.name, campaign.status FROM campaign
    ORDER BY campaign.id LIMIT 50". Use para qualquer consulta sem tool
    dedicada. Docs GAQL: developers.google.com/google-ads/api/docs/query/overview
    """
    return _rows(query, customer_id)


# ============================================================
# Campanhas
# ============================================================

@mcp.tool()
def list_campaigns(limit: int = 200, customer_id: str | None = None) -> Any:
    """Lista campanhas (id, nome, status, canal, orçamento) da conta."""
    q = (
        "SELECT campaign.id, campaign.name, campaign.status, "
        "campaign.advertising_channel_type, campaign_budget.amount_micros "
        f"FROM campaign ORDER BY campaign.id DESC LIMIT {int(limit)}"
    )
    return _rows(q, customer_id)


@mcp.tool()
def get_campaign(campaign_id: str, customer_id: str | None = None) -> Any:
    """Detalhes de uma campanha por id."""
    q = (
        "SELECT campaign.id, campaign.name, campaign.status, "
        "campaign.advertising_channel_type, campaign.bidding_strategy_type, "
        "campaign.start_date, campaign.end_date, campaign_budget.amount_micros "
        f"FROM campaign WHERE campaign.id = {int(campaign_id)}"
    )
    return _rows(q, customer_id)


@mcp.tool()
def create_campaign(
    name: str,
    daily_budget_units: float | None = None,
    budget_resource_name: str | None = None,
    channel_type: str = "SEARCH",
    bidding_strategy: str = "MANUAL_CPC",
    status: str = "PAUSED",
    start_date: str | None = None,
    end_date: str | None = None,
    customer_id: str | None = None,
) -> Any:
    """Cria uma campanha. Default: PAUSED (para não gastar acidentalmente).

    Orçamento: informe `budget_resource_name` (de create_campaign_budget) OU
    `daily_budget_units` (na moeda da conta, ex.: 50.0) — neste caso um
    CampaignBudget é criado automaticamente e vinculado.
    channel_type: SEARCH | DISPLAY | VIDEO | SHOPPING | PERFORMANCE_MAX.
    bidding_strategy: MANUAL_CPC | MAXIMIZE_CONVERSIONS | MAXIMIZE_CONVERSION_VALUE |
                      TARGET_SPEND (maximize clicks).
    status: PAUSED | ENABLED. Datas em 'YYYY-MM-DD'.
    """
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente"}

    # Resolve/cria o orçamento.
    if not budget_resource_name:
        if daily_budget_units is None:
            return {"error": "informe daily_budget_units ou budget_resource_name"}
        budget = create_campaign_budget(
            name=f"{name} — budget", daily_budget_units=daily_budget_units, customer_id=cid
        )
        if isinstance(budget, dict) and budget.get("error"):
            return budget
        budget_resource_name = budget["results"][0]

    try:
        op = client.get_type("CampaignOperation")
        c = op.create
        c.name = name
        c.status = client.enums.CampaignStatusEnum[status.upper()]
        c.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum[channel_type.upper()]
        # network_settings é obrigatório: a API rejeita a criação sem ele
        # (field_error=REQUIRED). Defaults sensatos por canal.
        ch = channel_type.upper()
        if ch == "SEARCH":
            c.network_settings.target_google_search = True
            c.network_settings.target_search_network = True
            c.network_settings.target_content_network = False
            c.network_settings.target_partner_search_network = False
        elif ch == "DISPLAY":
            c.network_settings.target_google_search = False
            c.network_settings.target_search_network = False
            c.network_settings.target_content_network = True
            c.network_settings.target_partner_search_network = False
        # Declaração obrigatória (API recente): publicidade política na UE.
        c.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
        c.campaign_budget = budget_resource_name
        # Estratégia de lance (oneof) — setar o sub-message ativa o oneof.
        bs = bidding_strategy.upper()
        if bs == "MANUAL_CPC":
            client.copy_from(c.manual_cpc, client.get_type("ManualCpc"))
        elif bs == "MAXIMIZE_CONVERSIONS":
            client.copy_from(c.maximize_conversions, client.get_type("MaximizeConversions"))
        elif bs == "MAXIMIZE_CONVERSION_VALUE":
            client.copy_from(c.maximize_conversion_value, client.get_type("MaximizeConversionValue"))
        elif bs == "TARGET_SPEND":
            client.copy_from(c.target_spend, client.get_type("TargetSpend"))
        else:
            return {"error": f"bidding_strategy inválida: {bidding_strategy}"}
        if start_date:
            c.start_date = start_date.replace("-", "")
        if end_date:
            c.end_date = end_date.replace("-", "")
        return _mutate("CampaignService", "mutate_campaigns", [op], cid)
    except Exception as e:  # noqa: BLE001
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        if isinstance(e, GoogleAdsException):
            return _gerr(e)
        return {"error": str(e)}


@mcp.tool()
def update_campaign(
    campaign_id: str,
    name: str | None = None,
    status: str | None = None,
    final_url_suffix: str | None = None,
    customer_id: str | None = None,
) -> Any:
    """Atualiza nome, status e/ou o sufixo de URL final de uma campanha.

    status: ENABLED | PAUSED | REMOVED.
    final_url_suffix: parâmetros anexados a TODAS as URLs finais da campanha (ex.:
    'utm_source=google&utm_medium=cpc&utm_campaign=autonext&utm_term={keyword}').
    Aceita ValueTrack ({keyword}, {campaignid}, {adgroupid}, {creative}...).
    """
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente"}
    try:
        from google.api_core import protobuf_helpers  # type: ignore
        service = client.get_service("CampaignService")
        op = client.get_type("CampaignOperation")
        c = op.update
        c.resource_name = service.campaign_path(cid, campaign_id)
        if name is not None:
            c.name = name
        if status is not None:
            c.status = client.enums.CampaignStatusEnum[status.upper()]
        if final_url_suffix is not None:
            c.final_url_suffix = final_url_suffix
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, c._pb))
        return _mutate("CampaignService", "mutate_campaigns", [op], cid)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def pause_campaign(campaign_id: str, customer_id: str | None = None) -> Any:
    """Pausa campanha (status -> PAUSED)."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    rn = client.get_service("CampaignService").campaign_path(cid, campaign_id)
    return _status_update("CampaignOperation", "CampaignService", "mutate_campaigns", rn, "PAUSED", cid)


@mcp.tool()
def resume_campaign(campaign_id: str, customer_id: str | None = None) -> Any:
    """Reativa campanha (status -> ENABLED)."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    rn = client.get_service("CampaignService").campaign_path(cid, campaign_id)
    return _status_update("CampaignOperation", "CampaignService", "mutate_campaigns", rn, "ENABLED", cid)


@mcp.tool()
def remove_campaign(campaign_id: str, customer_id: str | None = None) -> Any:
    """Remove campanha. DESTRUTIVO (equivale a deletar)."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    op = client.get_type("CampaignOperation")
    op.remove = client.get_service("CampaignService").campaign_path(cid, campaign_id)
    return _mutate("CampaignService", "mutate_campaigns", [op], cid)


# ============================================================
# Critérios de campanha (geo / idioma / negativas de campanha)
# ============================================================

@mcp.tool()
def add_geo_language(
    campaign_id: str,
    location_ids: list[str] | None = None,
    language_ids: list[str] | None = None,
    customer_id: str | None = None,
) -> Any:
    """Adiciona segmentação de LOCALIZAÇÃO e/ou IDIOMA a uma campanha.

    location_ids: ids de geoTargetConstants (ex.: ['2076'] = Brasil).
    language_ids: ids de languageConstants (ex.: ['1014'] = Português, '1000' = Inglês).
    Cria CampaignCriterion positivos. Sem isso a campanha mira o mundo todo /
    todos os idiomas — SEMPRE aplicar antes de ativar campanhas locais.
    """
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente"}
    location_ids = location_ids or []
    language_ids = language_ids or []
    if not location_ids and not language_ids:
        return {"error": "informe location_ids e/ou language_ids"}
    try:
        camp_path = client.get_service("CampaignService").campaign_path(cid, campaign_id)
        ops = []
        for loc in location_ids:
            op = client.get_type("CampaignCriterionOperation")
            crit = op.create
            crit.campaign = camp_path
            crit.location.geo_target_constant = f"geoTargetConstants/{str(loc).strip()}"
            ops.append(op)
        for lang in language_ids:
            op = client.get_type("CampaignCriterionOperation")
            crit = op.create
            crit.campaign = camp_path
            crit.language.language_constant = f"languageConstants/{str(lang).strip()}"
            ops.append(op)
        return _mutate("CampaignCriterionService", "mutate_campaign_criteria", ops, cid)
    except Exception as e:  # noqa: BLE001
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        if isinstance(e, GoogleAdsException):
            return _gerr(e)
        return {"error": str(e)}


@mcp.tool()
def add_campaign_negative_keywords(
    campaign_id: str,
    keywords: list[str],
    match_type: str = "BROAD",
    customer_id: str | None = None,
) -> Any:
    """Adiciona palavras-chave NEGATIVAS em nível de CAMPANHA (valem p/ todos os
    grupos). Ideal para negativas globais (grátis, pdf, torrent...) e negativas
    cruzadas entre campanhas. match_type: BROAD | PHRASE | EXACT."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente"}
    try:
        camp_path = client.get_service("CampaignService").campaign_path(cid, campaign_id)
        ops = []
        for kw in keywords:
            op = client.get_type("CampaignCriterionOperation")
            crit = op.create
            crit.campaign = camp_path
            crit.negative = True
            crit.keyword.text = kw
            crit.keyword.match_type = client.enums.KeywordMatchTypeEnum[match_type.upper()]
            ops.append(op)
        return _mutate("CampaignCriterionService", "mutate_campaign_criteria", ops, cid)
    except Exception as e:  # noqa: BLE001
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        if isinstance(e, GoogleAdsException):
            return _gerr(e)
        return {"error": str(e)}


# ============================================================
# Orçamentos (CampaignBudget)
# ============================================================

@mcp.tool()
def list_campaign_budgets(limit: int = 200, customer_id: str | None = None) -> Any:
    """Lista os orçamentos (id, nome, valor em micros, método de entrega)."""
    q = (
        "SELECT campaign_budget.id, campaign_budget.name, "
        "campaign_budget.amount_micros, campaign_budget.delivery_method, "
        "campaign_budget.explicitly_shared "
        f"FROM campaign_budget ORDER BY campaign_budget.id DESC LIMIT {int(limit)}"
    )
    return _rows(q, customer_id)


@mcp.tool()
def create_campaign_budget(
    name: str,
    daily_budget_units: float,
    delivery_method: str = "STANDARD",
    explicitly_shared: bool = False,
    customer_id: str | None = None,
) -> Any:
    """Cria um orçamento diário. `daily_budget_units` na moeda da conta (ex.: 50.0).

    delivery_method: STANDARD | ACCELERATED. explicitly_shared=False cria um
    orçamento dedicado a uma campanha. Retorna o resource_name para create_campaign.
    """
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente"}
    try:
        op = client.get_type("CampaignBudgetOperation")
        b = op.create
        b.name = name
        b.amount_micros = _to_micros(daily_budget_units)
        b.delivery_method = client.enums.BudgetDeliveryMethodEnum[delivery_method.upper()]
        b.explicitly_shared = explicitly_shared
        return _mutate("CampaignBudgetService", "mutate_campaign_budgets", [op], cid)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def update_campaign_budget(
    budget_id: str,
    name: str | None = None,
    daily_budget_units: float | None = None,
    customer_id: str | None = None,
) -> Any:
    """Atualiza nome e/ou valor (na moeda da conta) de um orçamento."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    try:
        from google.api_core import protobuf_helpers  # type: ignore
        service = client.get_service("CampaignBudgetService")
        op = client.get_type("CampaignBudgetOperation")
        b = op.update
        b.resource_name = service.campaign_budget_path(cid, budget_id)
        if name is not None:
            b.name = name
        if daily_budget_units is not None:
            b.amount_micros = _to_micros(daily_budget_units)
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, b._pb))
        return _mutate("CampaignBudgetService", "mutate_campaign_budgets", [op], cid)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def remove_campaign_budget(budget_id: str, customer_id: str | None = None) -> Any:
    """Remove um orçamento. DESTRUTIVO. Só funciona se reference_count == 0
    (nenhuma campanha usando); senão a API rejeita. Útil p/ limpar órfãos."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    op = client.get_type("CampaignBudgetOperation")
    op.remove = client.get_service("CampaignBudgetService").campaign_budget_path(cid, budget_id)
    return _mutate("CampaignBudgetService", "mutate_campaign_budgets", [op], cid)


# ============================================================
# Grupos de anúncios (Ad Groups)
# ============================================================

@mcp.tool()
def list_ad_groups(campaign_id: str | None = None, limit: int = 200,
                   customer_id: str | None = None) -> Any:
    """Lista grupos de anúncios; filtra por campaign_id se informado."""
    where = f" WHERE campaign.id = {int(campaign_id)}" if campaign_id else ""
    q = (
        "SELECT ad_group.id, ad_group.name, ad_group.status, ad_group.type, "
        "ad_group.cpc_bid_micros, campaign.id "
        f"FROM ad_group{where} ORDER BY ad_group.id DESC LIMIT {int(limit)}"
    )
    return _rows(q, customer_id)


@mcp.tool()
def create_ad_group(
    campaign_id: str,
    name: str,
    cpc_bid_units: float | None = None,
    status: str = "PAUSED",
    ad_group_type: str = "SEARCH_STANDARD",
    customer_id: str | None = None,
) -> Any:
    """Cria um grupo de anúncios numa campanha. Default: PAUSED.

    cpc_bid_units: lance de CPC na moeda da conta (ex.: 1.50). ad_group_type:
    SEARCH_STANDARD | DISPLAY_STANDARD | etc.
    """
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente"}
    try:
        op = client.get_type("AdGroupOperation")
        ag = op.create
        ag.name = name
        ag.campaign = client.get_service("CampaignService").campaign_path(cid, campaign_id)
        ag.status = client.enums.AdGroupStatusEnum[status.upper()]
        ag.type_ = client.enums.AdGroupTypeEnum[ad_group_type.upper()]
        micros = _to_micros(cpc_bid_units)
        if micros is not None:
            ag.cpc_bid_micros = micros
        return _mutate("AdGroupService", "mutate_ad_groups", [op], cid)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def update_ad_group(
    ad_group_id: str,
    name: str | None = None,
    status: str | None = None,
    cpc_bid_units: float | None = None,
    customer_id: str | None = None,
) -> Any:
    """Atualiza nome, status e/ou lance de CPC de um grupo de anúncios."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    try:
        from google.api_core import protobuf_helpers  # type: ignore
        service = client.get_service("AdGroupService")
        op = client.get_type("AdGroupOperation")
        ag = op.update
        ag.resource_name = service.ad_group_path(cid, ad_group_id)
        if name is not None:
            ag.name = name
        if status is not None:
            ag.status = client.enums.AdGroupStatusEnum[status.upper()]
        micros = _to_micros(cpc_bid_units)
        if micros is not None:
            ag.cpc_bid_micros = micros
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, ag._pb))
        return _mutate("AdGroupService", "mutate_ad_groups", [op], cid)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def pause_ad_group(ad_group_id: str, customer_id: str | None = None) -> Any:
    """Pausa grupo de anúncios (status -> PAUSED)."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    rn = client.get_service("AdGroupService").ad_group_path(cid, ad_group_id)
    return _status_update("AdGroupOperation", "AdGroupService", "mutate_ad_groups", rn, "PAUSED", cid)


@mcp.tool()
def resume_ad_group(ad_group_id: str, customer_id: str | None = None) -> Any:
    """Reativa grupo de anúncios (status -> ENABLED)."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    rn = client.get_service("AdGroupService").ad_group_path(cid, ad_group_id)
    return _status_update("AdGroupOperation", "AdGroupService", "mutate_ad_groups", rn, "ENABLED", cid)


@mcp.tool()
def remove_ad_group(ad_group_id: str, customer_id: str | None = None) -> Any:
    """Remove grupo de anúncios. DESTRUTIVO."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    op = client.get_type("AdGroupOperation")
    op.remove = client.get_service("AdGroupService").ad_group_path(cid, ad_group_id)
    return _mutate("AdGroupService", "mutate_ad_groups", [op], cid)


# ============================================================
# Anúncios (Ad Group Ads) — Responsive Search Ad
# ============================================================

@mcp.tool()
def list_ads(ad_group_id: str | None = None, limit: int = 200,
             customer_id: str | None = None) -> Any:
    """Lista anúncios; filtra por ad_group_id se informado."""
    where = f" WHERE ad_group.id = {int(ad_group_id)}" if ad_group_id else ""
    q = (
        "SELECT ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group_ad.status, "
        "ad_group_ad.ad.type, ad_group_ad.ad.final_urls, ad_group.id "
        f"FROM ad_group_ad{where} ORDER BY ad_group_ad.ad.id DESC LIMIT {int(limit)}"
    )
    return _rows(q, customer_id)


@mcp.tool()
def create_ad(
    ad_group_id: str,
    final_url: str,
    headlines: list[str],
    descriptions: list[str],
    path1: str | None = None,
    path2: str | None = None,
    status: str = "PAUSED",
    customer_id: str | None = None,
) -> Any:
    """Cria um Responsive Search Ad (RSA) num grupo. Default: PAUSED.

    headlines: 3 a 15 títulos (máx. 30 chars cada).
    descriptions: 2 a 4 descrições (máx. 90 chars cada).
    path1/path2: segmentos opcionais do display URL (máx. 15 chars).
    """
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente"}
    if len(headlines) < 3 or len(descriptions) < 2:
        return {"error": "RSA exige >=3 headlines e >=2 descriptions"}
    try:
        op = client.get_type("AdGroupAdOperation")
        aga = op.create
        aga.ad_group = client.get_service("AdGroupService").ad_group_path(cid, ad_group_id)
        aga.status = client.enums.AdGroupAdStatusEnum[status.upper()]
        ad = aga.ad
        ad.final_urls.append(final_url)
        rsa = ad.responsive_search_ad
        for text in headlines:
            asset = client.get_type("AdTextAsset")
            asset.text = text
            rsa.headlines.append(asset)
        for text in descriptions:
            asset = client.get_type("AdTextAsset")
            asset.text = text
            rsa.descriptions.append(asset)
        if path1:
            rsa.path1 = path1
        if path2:
            rsa.path2 = path2
        return _mutate("AdGroupAdService", "mutate_ad_group_ads", [op], cid)
    except Exception as e:  # noqa: BLE001
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        if isinstance(e, GoogleAdsException):
            return _gerr(e)
        return {"error": str(e)}


@mcp.tool()
def update_ad(ad_id: str, final_url: str, customer_id: str | None = None) -> Any:
    """Atualiza a URL final (final_url) de um anúncio existente.

    Obs.: em RSA os textos (headlines/descriptions) NÃO são editáveis via API —
    para trocar textos, recrie o anúncio. A URL final é editável.
    """
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente"}
    try:
        from google.api_core import protobuf_helpers  # type: ignore
        svc = client.get_service("AdService")
        op = client.get_type("AdOperation")
        ad = op.update
        ad.resource_name = svc.ad_path(cid, ad_id)
        ad.final_urls.append(final_url)
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, ad._pb))
        return _mutate("AdService", "mutate_ads", [op], cid)
    except Exception as e:  # noqa: BLE001
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        if isinstance(e, GoogleAdsException):
            return _gerr(e)
        return {"error": str(e)}


@mcp.tool()
def pause_ad(ad_group_id: str, ad_id: str, customer_id: str | None = None) -> Any:
    """Pausa anúncio (status -> PAUSED)."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    rn = client.get_service("AdGroupAdService").ad_group_ad_path(cid, ad_group_id, ad_id)
    return _status_update("AdGroupAdOperation", "AdGroupAdService", "mutate_ad_group_ads", rn, "PAUSED", cid)


@mcp.tool()
def resume_ad(ad_group_id: str, ad_id: str, customer_id: str | None = None) -> Any:
    """Reativa anúncio (status -> ENABLED)."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    rn = client.get_service("AdGroupAdService").ad_group_ad_path(cid, ad_group_id, ad_id)
    return _status_update("AdGroupAdOperation", "AdGroupAdService", "mutate_ad_group_ads", rn, "ENABLED", cid)


@mcp.tool()
def remove_ad(ad_group_id: str, ad_id: str, customer_id: str | None = None) -> Any:
    """Remove anúncio. DESTRUTIVO."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    op = client.get_type("AdGroupAdOperation")
    op.remove = client.get_service("AdGroupAdService").ad_group_ad_path(cid, ad_group_id, ad_id)
    return _mutate("AdGroupAdService", "mutate_ad_group_ads", [op], cid)


# ============================================================
# Palavras-chave (Ad Group Criteria)
# ============================================================

@mcp.tool()
def list_keywords(ad_group_id: str | None = None, limit: int = 500,
                  customer_id: str | None = None) -> Any:
    """Lista palavras-chave (positivas e negativas); filtra por ad_group_id."""
    where = f"ad_group.id = {int(ad_group_id)} AND " if ad_group_id else ""
    q = (
        "SELECT ad_group_criterion.criterion_id, ad_group_criterion.keyword.text, "
        "ad_group_criterion.keyword.match_type, ad_group_criterion.status, "
        "ad_group_criterion.negative, ad_group.id "
        f"FROM ad_group_criterion WHERE {where}ad_group_criterion.type = KEYWORD "
        f"LIMIT {int(limit)}"
    )
    return _rows(q, customer_id)


def _add_keywords(ad_group_id: str, keywords: list[str], match_type: str,
                  negative: bool, cid: str) -> Any:
    client = _client()
    if isinstance(client, dict):
        return client
    try:
        ag_path = client.get_service("AdGroupService").ad_group_path(cid, ad_group_id)
        ops = []
        for kw in keywords:
            op = client.get_type("AdGroupCriterionOperation")
            crit = op.create
            crit.ad_group = ag_path
            crit.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
            crit.keyword.text = kw
            crit.keyword.match_type = client.enums.KeywordMatchTypeEnum[match_type.upper()]
            if negative:
                crit.negative = True
            ops.append(op)
        return _mutate("AdGroupCriterionService", "mutate_ad_group_criteria", ops, cid)
    except Exception as e:  # noqa: BLE001
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        if isinstance(e, GoogleAdsException):
            return _gerr(e)
        return {"error": str(e)}


@mcp.tool()
def add_keywords(ad_group_id: str, keywords: list[str], match_type: str = "BROAD",
                 customer_id: str | None = None) -> Any:
    """Adiciona palavras-chave positivas a um grupo. match_type: BROAD | PHRASE | EXACT."""
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente"}
    return _add_keywords(ad_group_id, keywords, match_type, negative=False, cid=cid)


@mcp.tool()
def add_negative_keywords(ad_group_id: str, keywords: list[str], match_type: str = "BROAD",
                          customer_id: str | None = None) -> Any:
    """Adiciona palavras-chave NEGATIVAS a um grupo. match_type: BROAD | PHRASE | EXACT."""
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente"}
    return _add_keywords(ad_group_id, keywords, match_type, negative=True, cid=cid)


@mcp.tool()
def pause_keyword(ad_group_id: str, criterion_id: str, customer_id: str | None = None) -> Any:
    """Pausa uma palavra-chave (status -> PAUSED)."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    rn = client.get_service("AdGroupCriterionService").ad_group_criterion_path(cid, ad_group_id, criterion_id)
    return _status_update("AdGroupCriterionOperation", "AdGroupCriterionService",
                          "mutate_ad_group_criteria", rn, "PAUSED", cid)


@mcp.tool()
def resume_keyword(ad_group_id: str, criterion_id: str, customer_id: str | None = None) -> Any:
    """Reativa uma palavra-chave (status -> ENABLED)."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    rn = client.get_service("AdGroupCriterionService").ad_group_criterion_path(cid, ad_group_id, criterion_id)
    return _status_update("AdGroupCriterionOperation", "AdGroupCriterionService",
                          "mutate_ad_group_criteria", rn, "ENABLED", cid)


@mcp.tool()
def remove_keyword(ad_group_id: str, criterion_id: str, customer_id: str | None = None) -> Any:
    """Remove uma palavra-chave. DESTRUTIVO."""
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    op = client.get_type("AdGroupCriterionOperation")
    op.remove = client.get_service("AdGroupCriterionService").ad_group_criterion_path(cid, ad_group_id, criterion_id)
    return _mutate("AdGroupCriterionService", "mutate_ad_group_criteria", [op], cid)


# ============================================================
# Conversões (ConversionAction)
# ============================================================

@mcp.tool()
def list_conversion_actions(customer_id: str | None = None) -> Any:
    """Lista as ações de conversão (id, nome, status, tipo, categoria)."""
    q = (
        "SELECT conversion_action.id, conversion_action.name, conversion_action.status, "
        "conversion_action.type, conversion_action.category "
        "FROM conversion_action ORDER BY conversion_action.id DESC"
    )
    return _rows(q, customer_id)


@mcp.tool()
def create_conversion_action(
    name: str,
    category: str = "PURCHASE",
    action_type: str = "WEBPAGE",
    status: str = "ENABLED",
    default_value: float | None = None,
    always_use_default_value: bool = False,
    counting_type: str = "ONE_PER_CLICK",
    customer_id: str | None = None,
) -> Any:
    """Cria uma ação de conversão (ex.: compra de curso via Hotmart).

    category: PURCHASE | LEAD | SIGN_UP | BEGIN_CHECKOUT | DEFAULT ...
    action_type: WEBPAGE (tag no site) é o padrão. status: ENABLED | PAUSED.
    counting_type: ONE_PER_CLICK (1 por clique, ideal p/ lead/venda de curso) |
                   MANY_PER_CLICK (ecommerce). Ao criar WEBPAGE, a API gera os
                   tag_snippets (global tag + event snippet) — leia depois com
                   uma GAQL em conversion_action.tag_snippets p/ instalar/ligar
                   no Hotmart (Conversion ID + Label).
    """
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente"}
    try:
        op = client.get_type("ConversionActionOperation")
        ca = op.create
        ca.name = name
        ca.type_ = client.enums.ConversionActionTypeEnum[action_type.upper()]
        ca.category = client.enums.ConversionActionCategoryEnum[category.upper()]
        ca.status = client.enums.ConversionActionStatusEnum[status.upper()]
        ca.counting_type = client.enums.ConversionActionCountingTypeEnum[counting_type.upper()]
        if default_value is not None:
            ca.value_settings.default_value = float(default_value)
        ca.value_settings.always_use_default_value = bool(always_use_default_value)
        return _mutate("ConversionActionService", "mutate_conversion_actions", [op], cid)
    except Exception as e:  # noqa: BLE001
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        if isinstance(e, GoogleAdsException):
            return _gerr(e)
        return {"error": str(e)}


# ============================================================
# Relatórios / Insights
# ============================================================

_INSIGHT_LEVEL = {
    "campaign": ("campaign", "campaign.id, campaign.name"),
    "ad_group": ("ad_group", "ad_group.id, ad_group.name"),
    "ad": ("ad_group_ad", "ad_group_ad.ad.id, ad_group_ad.ad.name"),
}


@mcp.tool()
def get_insights(
    level: str = "campaign",
    date_preset: str = "LAST_30_DAYS",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 200,
    customer_id: str | None = None,
) -> Any:
    """Métricas de performance por nível. Monta uma GAQL sob o capô.

    level: campaign | ad_group | ad.
    date_preset: LAST_7_DAYS | LAST_30_DAYS | THIS_MONTH | LAST_MONTH | TODAY |
                 YESTERDAY (ignorado se start_date/end_date forem informados).
    Datas em 'YYYY-MM-DD'. Métricas: impressions, clicks, cost (micros),
    conversions, ctr, average_cpc.
    """
    if level not in _INSIGHT_LEVEL:
        return {"error": f"level inválido: {level} (use campaign|ad_group|ad)"}
    resource, dims = _INSIGHT_LEVEL[level]
    metrics = ("metrics.impressions, metrics.clicks, metrics.cost_micros, "
               "metrics.conversions, metrics.ctr, metrics.average_cpc")
    if start_date and end_date:
        date_clause = f"segments.date BETWEEN '{start_date}' AND '{end_date}'"
    else:
        date_clause = f"segments.date DURING {date_preset.upper()}"
    q = (
        f"SELECT {dims}, {metrics} FROM {resource} WHERE {date_clause} "
        f"ORDER BY metrics.impressions DESC LIMIT {int(limit)}"
    )
    return _rows(q, customer_id)


@mcp.tool()
def search_terms_report(
    date_preset: str = "LAST_30_DAYS",
    limit: int = 200,
    customer_id: str | None = None,
) -> Any:
    """Relatório de termos de busca (o que as pessoas digitaram) com métricas."""
    q = (
        "SELECT search_term_view.search_term, segments.keyword.info.text, "
        "metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions "
        f"FROM search_term_view WHERE segments.date DURING {date_preset.upper()} "
        f"ORDER BY metrics.impressions DESC LIMIT {int(limit)}"
    )
    return _rows(q, customer_id)


# ============================================================
# Keyword Planner (ideias + volume de busca)
# ============================================================

@mcp.tool()
def keyword_ideas(
    seeds: list[str] | None = None,
    url: str | None = None,
    language_id: str = "1014",
    location_ids: list[str] | None = None,
    keyword_plan_network: str = "GOOGLE_SEARCH",
    limit: int = 200,
    customer_id: str | None = None,
) -> Any:
    """Pesquisa ideias de palavras-chave com VOLUME DE BUSCA (Keyword Planner).

    Use `seeds` (termos semente) e/ou `url` (página de destino — o Google extrai
    keywords do conteúdo). language_id: 1014=PT, 1000=EN. location_ids: ['2076']=Brasil.
    keyword_plan_network: GOOGLE_SEARCH | GOOGLE_SEARCH_AND_PARTNERS.
    Retorna, por ideia: texto, buscas mensais médias, concorrência (LOW/MEDIUM/HIGH)
    e faixa de lance de topo (low/high, na moeda da conta). Ordenado por volume desc.
    """
    client = _client()
    if isinstance(client, dict):
        return client
    cid = _resolve_cid(customer_id)
    if not cid:
        return {"error": "customer_id ausente"}
    seeds = [s for s in (seeds or []) if s.strip()]
    location_ids = location_ids or ["2076"]
    if not seeds and not url:
        return {"error": "informe seeds e/ou url"}
    try:
        svc = client.get_service("KeywordPlanIdeaService")
        req = client.get_type("GenerateKeywordIdeasRequest")
        req.customer_id = cid
        req.language = f"languageConstants/{language_id}"
        for loc in location_ids:
            req.geo_target_constants.append(f"geoTargetConstants/{loc}")
        req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum[keyword_plan_network.upper()]
        if seeds and url:
            req.keyword_and_url_seed.url = url
            req.keyword_and_url_seed.keywords.extend(seeds)
        elif url:
            req.url_seed.url = url
        else:
            req.keyword_seed.keywords.extend(seeds)
        out = []
        for idea in svc.generate_keyword_ideas(request=req):
            m = idea.keyword_idea_metrics
            out.append({
                "text": idea.text,
                "avg_monthly_searches": int(m.avg_monthly_searches or 0),
                "competition": m.competition.name if m.competition else "UNKNOWN",
                "competition_index": int(m.competition_index or 0),
                "low_top_bid": round((m.low_top_of_page_bid_micros or 0) / 1_000_000, 2),
                "high_top_bid": round((m.high_top_of_page_bid_micros or 0) / 1_000_000, 2),
            })
        out.sort(key=lambda x: x["avg_monthly_searches"], reverse=True)
        return out[: int(limit)]
    except Exception as e:  # noqa: BLE001
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        if isinstance(e, GoogleAdsException):
            return _gerr(e)
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run()
