#!/usr/bin/env python3
"""CLI `googleads` — front-end de terminal do MCP de Google Ads.

Consolida TUDO num comando só: autenticação (gera o refresh_token OAuth),
leituras (campanhas, insights, GAQL...) e escritas (criar/pausar/remover).
Reaproveita as mesmas funções do MCP (`google_ads_cli_mcp.py`), então CLI e
agentes (OpenClaw/Hermes) fazem exatamente as mesmas operações.

Uso (dentro do container):
  googleads auth                      # gera o refresh_token (fluxo OAuth headless)
  googleads accounts                  # contas acessiveis
  googleads campaigns --limit 20      # lista campanhas
  googleads insights --preset LAST_30_DAYS
  googleads gaql "SELECT campaign.id, campaign.name FROM campaign LIMIT 10"
  googleads create-campaign --name "Teste" --daily 50   # nasce PAUSED
  googleads pause-campaign 23207245140

Do host: `docker compose exec -it openclaw-vibestack googleads <cmd>`.
Toda saida e' JSON. Toda operacao aceita --customer-id p/ mirar outra conta.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")


def _g():
    """Importa o modulo do MCP (lazy, p/ o --help nao exigir o SDK)."""
    import middleware.google_ads_cli_mcp as g  # type: ignore
    return g


def _out(result) -> int:
    """Imprime o resultado como JSON. Sai 1 se for um dict de erro."""
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if isinstance(result, dict) and result.get("error"):
        return 1
    return 0


def _cid(args):
    return getattr(args, "customer_id", None)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="googleads",
        description="CLI do Google Ads (auth + leituras + escritas) — mesmo backend dos agentes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", metavar="<comando>")

    def add(name, help_, writes=False):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--customer-id", help="conta a operar (sem hifens); default = GOOGLE_ADS_CUSTOMER_ID")
        return sp

    # ---- Auth -------------------------------------------------------------
    sub.add_parser("auth", help="[auth] gera o refresh_token OAuth (fluxo headless)")

    # ---- Leituras ---------------------------------------------------------
    add("accounts", "[leitura] contas acessiveis pelo refresh_token")
    add("whoami", "[leitura] conta ativa + MCC de login")

    sp = add("campaigns", "[leitura] lista campanhas")
    sp.add_argument("--limit", type=int, default=200)

    sp = add("campaign", "[leitura] detalhes de 1 campanha")
    sp.add_argument("id")

    sp = add("budgets", "[leitura] lista orcamentos")
    sp.add_argument("--limit", type=int, default=200)

    sp = add("ad-groups", "[leitura] lista grupos de anuncios")
    sp.add_argument("--campaign", help="filtra por campaign_id")
    sp.add_argument("--limit", type=int, default=200)

    sp = add("ads", "[leitura] lista anuncios")
    sp.add_argument("--ad-group", help="filtra por ad_group_id")
    sp.add_argument("--limit", type=int, default=200)

    sp = add("keywords", "[leitura] lista palavras-chave")
    sp.add_argument("--ad-group", help="filtra por ad_group_id")
    sp.add_argument("--limit", type=int, default=500)

    sp = add("insights", "[leitura] metricas de performance")
    sp.add_argument("--level", default="campaign", choices=["campaign", "ad_group", "ad"])
    sp.add_argument("--preset", default="LAST_30_DAYS", help="LAST_7_DAYS|LAST_30_DAYS|THIS_MONTH|LAST_MONTH|TODAY|YESTERDAY")
    sp.add_argument("--start", help="YYYY-MM-DD (usa com --end, ignora o preset)")
    sp.add_argument("--end", help="YYYY-MM-DD")
    sp.add_argument("--limit", type=int, default=200)

    sp = add("search-terms", "[leitura] relatorio de termos de busca")
    sp.add_argument("--preset", default="LAST_30_DAYS")
    sp.add_argument("--limit", type=int, default=200)

    sp = add("gaql", "[leitura] executa uma query GAQL arbitraria")
    sp.add_argument("query", help="ex.: 'SELECT campaign.id, campaign.name FROM campaign LIMIT 10'")

    # ---- Escritas ---------------------------------------------------------
    sp = add("create-budget", "[escrita] cria orcamento diario")
    sp.add_argument("--name", required=True)
    sp.add_argument("--daily", type=float, required=True, help="valor/dia na moeda da conta (ex.: 50.0)")
    sp.add_argument("--delivery", default="STANDARD", choices=["STANDARD", "ACCELERATED"])
    sp.add_argument("--shared", action="store_true", help="orcamento compartilhado (default: dedicado)")

    sp = add("create-campaign", "[escrita] cria campanha (nasce PAUSED)")
    sp.add_argument("--name", required=True)
    sp.add_argument("--daily", type=float, help="cria um orcamento diario e vincula (na moeda da conta)")
    sp.add_argument("--budget-resource", help="resource_name de um orcamento existente")
    sp.add_argument("--channel", default="SEARCH", help="SEARCH|DISPLAY|VIDEO|SHOPPING|PERFORMANCE_MAX")
    sp.add_argument("--bidding", default="MANUAL_CPC", help="MANUAL_CPC|MAXIMIZE_CONVERSIONS|MAXIMIZE_CONVERSION_VALUE|TARGET_SPEND")
    sp.add_argument("--status", default="PAUSED", help="PAUSED|ENABLED")
    sp.add_argument("--start", help="YYYY-MM-DD")
    sp.add_argument("--end", help="YYYY-MM-DD")

    sp = add("update-campaign", "[escrita] atualiza nome/status de campanha")
    sp.add_argument("id")
    sp.add_argument("--name")
    sp.add_argument("--status", help="ENABLED|PAUSED|REMOVED")

    sp = add("pause-campaign", "[escrita] pausa campanha")
    sp.add_argument("id")
    sp = add("resume-campaign", "[escrita] reativa campanha")
    sp.add_argument("id")
    sp = add("remove-campaign", "[escrita] remove campanha (DESTRUTIVO)")
    sp.add_argument("id")

    sp = add("update-budget", "[escrita] atualiza nome/valor de orcamento")
    sp.add_argument("id")
    sp.add_argument("--name")
    sp.add_argument("--daily", type=float, help="novo valor/dia na moeda da conta")

    sp = add("create-ad-group", "[escrita] cria grupo de anuncios (nasce PAUSED)")
    sp.add_argument("--campaign", required=True, help="campaign_id")
    sp.add_argument("--name", required=True)
    sp.add_argument("--cpc", type=float, help="lance de CPC na moeda da conta (ex.: 1.5)")
    sp.add_argument("--status", default="PAUSED")
    sp.add_argument("--type", default="SEARCH_STANDARD")

    sp = add("update-ad-group", "[escrita] atualiza grupo de anuncios")
    sp.add_argument("id")
    sp.add_argument("--name")
    sp.add_argument("--status")
    sp.add_argument("--cpc", type=float)

    sp = add("pause-ad-group", "[escrita] pausa grupo de anuncios")
    sp.add_argument("id")
    sp = add("remove-ad-group", "[escrita] remove grupo de anuncios (DESTRUTIVO)")
    sp.add_argument("id")

    sp = add("create-ad", "[escrita] cria Responsive Search Ad (nasce PAUSED)")
    sp.add_argument("--ad-group", required=True, help="ad_group_id")
    sp.add_argument("--url", required=True, help="final URL")
    sp.add_argument("--headline", action="append", default=[], help="titulo (repita >=3x, max 30 chars)")
    sp.add_argument("--description", action="append", default=[], help="descricao (repita >=2x, max 90 chars)")
    sp.add_argument("--path1")
    sp.add_argument("--path2")
    sp.add_argument("--status", default="PAUSED")

    sp = add("pause-ad", "[escrita] pausa anuncio")
    sp.add_argument("--ad-group", required=True)
    sp.add_argument("--ad", required=True)
    sp = add("remove-ad", "[escrita] remove anuncio (DESTRUTIVO)")
    sp.add_argument("--ad-group", required=True)
    sp.add_argument("--ad", required=True)

    sp = add("add-keywords", "[escrita] adiciona palavras-chave positivas")
    sp.add_argument("--ad-group", required=True)
    sp.add_argument("--keyword", action="append", default=[], required=True, help="repita p/ varias")
    sp.add_argument("--match", default="BROAD", choices=["BROAD", "PHRASE", "EXACT"])

    sp = add("add-negative-keywords", "[escrita] adiciona palavras-chave NEGATIVAS")
    sp.add_argument("--ad-group", required=True)
    sp.add_argument("--keyword", action="append", default=[], required=True)
    sp.add_argument("--match", default="BROAD", choices=["BROAD", "PHRASE", "EXACT"])

    sp = add("pause-keyword", "[escrita] pausa palavra-chave")
    sp.add_argument("--ad-group", required=True)
    sp.add_argument("--criterion", required=True)
    sp = add("remove-keyword", "[escrita] remove palavra-chave (DESTRUTIVO)")
    sp.add_argument("--ad-group", required=True)
    sp.add_argument("--criterion", required=True)

    return p


def dispatch(args) -> int:
    cmd = args.cmd
    if cmd == "auth":
        import middleware.google_ads_auth as auth  # type: ignore
        return auth.main()

    g = _g()
    cid = _cid(args)

    # Leituras
    if cmd == "accounts":
        return _out(g.list_accessible_customers())
    if cmd == "whoami":
        return _out(g.current_customer())
    if cmd == "campaigns":
        return _out(g.list_campaigns(limit=args.limit, customer_id=cid))
    if cmd == "campaign":
        return _out(g.get_campaign(args.id, customer_id=cid))
    if cmd == "budgets":
        return _out(g.list_campaign_budgets(limit=args.limit, customer_id=cid))
    if cmd == "ad-groups":
        return _out(g.list_ad_groups(campaign_id=args.campaign, limit=args.limit, customer_id=cid))
    if cmd == "ads":
        return _out(g.list_ads(ad_group_id=args.ad_group, limit=args.limit, customer_id=cid))
    if cmd == "keywords":
        return _out(g.list_keywords(ad_group_id=args.ad_group, limit=args.limit, customer_id=cid))
    if cmd == "insights":
        return _out(g.get_insights(level=args.level, date_preset=args.preset,
                                   start_date=args.start, end_date=args.end,
                                   limit=args.limit, customer_id=cid))
    if cmd == "search-terms":
        return _out(g.search_terms_report(date_preset=args.preset, limit=args.limit, customer_id=cid))
    if cmd == "gaql":
        return _out(g.gaql_search(args.query, customer_id=cid))

    # Escritas
    if cmd == "create-budget":
        return _out(g.create_campaign_budget(name=args.name, daily_budget_units=args.daily,
                                             delivery_method=args.delivery,
                                             explicitly_shared=args.shared, customer_id=cid))
    if cmd == "create-campaign":
        return _out(g.create_campaign(name=args.name, daily_budget_units=args.daily,
                                      budget_resource_name=args.budget_resource,
                                      channel_type=args.channel, bidding_strategy=args.bidding,
                                      status=args.status, start_date=args.start,
                                      end_date=args.end, customer_id=cid))
    if cmd == "update-campaign":
        return _out(g.update_campaign(args.id, name=args.name, status=args.status, customer_id=cid))
    if cmd == "pause-campaign":
        return _out(g.pause_campaign(args.id, customer_id=cid))
    if cmd == "resume-campaign":
        return _out(g.resume_campaign(args.id, customer_id=cid))
    if cmd == "remove-campaign":
        return _out(g.remove_campaign(args.id, customer_id=cid))
    if cmd == "update-budget":
        return _out(g.update_campaign_budget(args.id, name=args.name,
                                             daily_budget_units=args.daily, customer_id=cid))
    if cmd == "create-ad-group":
        return _out(g.create_ad_group(campaign_id=args.campaign, name=args.name,
                                      cpc_bid_units=args.cpc, status=args.status,
                                      ad_group_type=args.type, customer_id=cid))
    if cmd == "update-ad-group":
        return _out(g.update_ad_group(args.id, name=args.name, status=args.status,
                                      cpc_bid_units=args.cpc, customer_id=cid))
    if cmd == "pause-ad-group":
        return _out(g.pause_ad_group(args.id, customer_id=cid))
    if cmd == "remove-ad-group":
        return _out(g.remove_ad_group(args.id, customer_id=cid))
    if cmd == "create-ad":
        return _out(g.create_ad(ad_group_id=args.ad_group, final_url=args.url,
                                headlines=args.headline, descriptions=args.description,
                                path1=args.path1, path2=args.path2,
                                status=args.status, customer_id=cid))
    if cmd == "pause-ad":
        return _out(g.pause_ad(args.ad_group, args.ad, customer_id=cid))
    if cmd == "remove-ad":
        return _out(g.remove_ad(args.ad_group, args.ad, customer_id=cid))
    if cmd == "add-keywords":
        return _out(g.add_keywords(args.ad_group, args.keyword, match_type=args.match, customer_id=cid))
    if cmd == "add-negative-keywords":
        return _out(g.add_negative_keywords(args.ad_group, args.keyword, match_type=args.match, customer_id=cid))
    if cmd == "pause-keyword":
        return _out(g.pause_keyword(args.ad_group, args.criterion, customer_id=cid))
    if cmd == "remove-keyword":
        return _out(g.remove_keyword(args.ad_group, args.criterion, customer_id=cid))

    return 2  # nao deveria chegar aqui


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return 0
    return dispatch(args)


if __name__ == "__main__":
    raise SystemExit(main())
