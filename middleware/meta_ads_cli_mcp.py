#!/usr/bin/env python3
"""MCP server stdio que expõe a Meta Ads CLI oficial (`meta`) como tools tipados.

O openclaw spawna este script como subprocesso (config em openclaw.json).
Cada tool traduz uma chamada MCP em `subprocess.run(["meta", "ads", ...])`,
sempre com `--output json`, e devolve o JSON parseado.

Auth: a CLI lê ACCESS_TOKEN e AD_ACCOUNT_ID do env. Esses já são injetados
pelo docker-compose no env do container openclaw-gateway, e subprocessos
herdam — nada a fazer aqui.

Pacote: https://pypi.org/project/meta-ads/  (v1.0.1, oficial Meta).
"""
import json
import subprocess
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("meta-ads-cli")
CLI = "meta"


def _run(*args: str) -> Any:
    """Executa `meta ads <args> --output json` e devolve dict/list.

    Em caso de erro (returncode != 0), devolve dict com 'error' + 'cmd' pra o
    agente diagnosticar; não levanta exception (MCP lida melhor com dict).
    """
    cmd = [CLI, "ads", *args, "--output", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return {
            "error": r.stderr.strip() or f"exit {r.returncode}",
            "cmd": " ".join(cmd),
        }
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"raw": r.stdout}


# ============================================================
# Ad Accounts
# ============================================================

@mcp.tool()
def list_ad_accounts() -> Any:
    """Lista todas as ad accounts acessíveis pelo ACCESS_TOKEN configurado."""
    return _run("adaccount", "list")


@mcp.tool()
def get_ad_account(ad_account_id: str) -> Any:
    """Detalhes de uma ad account. Formato: 'act_123456789'."""
    return _run("adaccount", "get", ad_account_id)


@mcp.tool()
def current_ad_account() -> Any:
    """Ad account ativa (definida em AD_ACCOUNT_ID)."""
    return _run("adaccount", "current")


# ============================================================
# Campaigns
# ============================================================

@mcp.tool()
def list_campaigns() -> Any:
    """Lista campanhas da ad account ativa (AD_ACCOUNT_ID)."""
    return _run("campaign", "list")


@mcp.tool()
def get_campaign(campaign_id: str) -> Any:
    """Detalhes de uma campanha específica."""
    return _run("campaign", "get", campaign_id)


@mcp.tool()
def create_campaign(name: str, objective: str, daily_budget_cents: int) -> Any:
    """Cria uma campanha.

    objective: ex. 'OUTCOME_SALES', 'OUTCOME_TRAFFIC', 'OUTCOME_LEADS',
               'OUTCOME_AWARENESS', 'OUTCOME_ENGAGEMENT', 'OUTCOME_APP_PROMOTION'.
    daily_budget_cents: orçamento diário em centavos da moeda da conta.
    """
    return _run(
        "campaign", "create",
        "--name", name,
        "--objective", objective,
        "--daily-budget", str(daily_budget_cents),
    )


@mcp.tool()
def delete_campaign(campaign_id: str) -> Any:
    """Deleta (arquiva) uma campanha. Operação destrutiva — confirmar antes."""
    return _run("campaign", "delete", campaign_id)


# ============================================================
# Ad Sets
# ============================================================

@mcp.tool()
def list_ad_sets() -> Any:
    """Lista ad sets da ad account ativa."""
    return _run("adset", "list")


@mcp.tool()
def get_ad_set(ad_set_id: str) -> Any:
    """Detalhes de um ad set."""
    return _run("adset", "get", ad_set_id)


# ============================================================
# Ads
# ============================================================

@mcp.tool()
def list_ads() -> Any:
    """Lista ads da ad account ativa."""
    return _run("ad", "list")


@mcp.tool()
def get_ad(ad_id: str) -> Any:
    """Detalhes de um ad."""
    return _run("ad", "get", ad_id)


# ============================================================
# Creatives
# ============================================================

@mcp.tool()
def list_creatives() -> Any:
    """Lista creatives da ad account ativa."""
    return _run("creative", "list")


@mcp.tool()
def get_creative(creative_id: str) -> Any:
    """Detalhes de um creative."""
    return _run("creative", "get", creative_id)


# ============================================================
# Insights (métricas de performance)
# ============================================================

@mcp.tool()
def get_insights(
    date_preset: str = "last_7d",
    level: str | None = None,
) -> Any:
    """Métricas (impressões, cliques, gasto, CPC, CPM, conversões) da conta ativa.

    date_preset: 'today', 'yesterday', 'last_7d', 'last_14d', 'last_30d',
                 'last_90d', 'this_month', 'last_month', 'maximum'.
    level: 'account' (default), 'campaign', 'adset', 'ad' — agregação.
    """
    args = ["insights", "get", "--date-preset", date_preset]
    if level:
        args += ["--level", level]
    return _run(*args)


# ============================================================
# Catalog / Product (e-commerce)
# ============================================================

@mcp.tool()
def list_catalogs() -> Any:
    """Lista product catalogs do business."""
    return _run("catalog", "list")


@mcp.tool()
def list_pages() -> Any:
    """Lista business pages associadas."""
    return _run("page", "list")


if __name__ == "__main__":
    mcp.run()
