#!/usr/bin/env python3
"""Gera um refresh_token OAuth do Google Ads em ambiente HEADLESS (container).

Fluxo (padrão do generate_user_credentials.py oficial do google-ads-python):
  1. Lê GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET do ambiente.
  2. Imprime uma URL de consentimento — o aluno abre no navegador DELE.
  3. O navegador redireciona para http://localhost:<porta> (que não existe aqui);
     a página falha, mas a barra de endereço contém `?code=...`.
  4. O aluno cola a URL completa de redirecionamento (ou só o code) de volta.
  5. Trocamos o code por tokens e IMPRIMIMOS o refresh_token.

O script NÃO grava nada: o aluno copia o refresh_token para GOOGLE_ADS_REFRESH_TOKEN
no .env do host e roda `docker compose up -d` de novo.

IMPORTANTE: o OAuth client tem que ser do tipo "Desktop app" (ou "Web" com
http://localhost autorizado). Clients Desktop permitem o redirect loopback com
qualquer porta automaticamente.

Uso: docker compose exec -it openclaw-vibestack google-ads-auth
"""
import os
import sys
from urllib.parse import parse_qs, urlparse

SCOPES = ["https://www.googleapis.com/auth/adwords"]
REDIRECT_URI = "http://localhost:8080"


def main() -> int:
    client_id = os.environ.get("GOOGLE_ADS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("ERRO: defina GOOGLE_ADS_CLIENT_ID e GOOGLE_ADS_CLIENT_SECRET no .env "
              "antes de rodar (crie um OAuth client 'Desktop app' no Google Cloud).",
              file=sys.stderr)
        return 1

    try:
        from google_auth_oauthlib.flow import Flow  # type: ignore
    except Exception as e:  # noqa: BLE001
        print(f"ERRO: google-auth-oauthlib indisponível no venv: {e}", file=sys.stderr)
        return 1

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI

    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent",
                                         include_granted_scopes="true")
    print("\n=== Google Ads — geração de refresh token ===\n")
    print("1) Abra esta URL no seu navegador e autorize a conta do Google Ads:\n")
    print(auth_url + "\n")
    print("2) O navegador vai tentar abrir 'http://localhost:8080/?code=...' e FALHAR "
          "(normal). Copie a URL inteira da barra de endereço.\n")

    raw = input("Cole aqui a URL de redirecionamento completa (ou só o code): ").strip()
    if not raw:
        print("ERRO: nada colado.", file=sys.stderr)
        return 1

    code = raw
    if "code=" in raw:
        qs = parse_qs(urlparse(raw).query)
        code = (qs.get("code") or [""])[0]
    if not code:
        print("ERRO: não achei o 'code' na URL colada.", file=sys.stderr)
        return 1

    try:
        flow.fetch_token(code=code)
    except Exception as e:  # noqa: BLE001
        print(f"ERRO ao trocar o code por tokens: {e}", file=sys.stderr)
        return 1

    refresh_token = getattr(flow.credentials, "refresh_token", None)
    if not refresh_token:
        print("ERRO: o Google não devolveu refresh_token. Revogue o acesso do app em "
              "https://myaccount.google.com/permissions e tente de novo (prompt=consent).",
              file=sys.stderr)
        return 1

    print("\n=== PRONTO ===")
    print("Cole no .env do host e rode `docker compose up -d`:\n")
    print(f"GOOGLE_ADS_REFRESH_TOKEN={refresh_token}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
