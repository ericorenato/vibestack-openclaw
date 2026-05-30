#!/usr/bin/env python3
"""MCP server stdio que expõe o envio de WhatsApp via Evolution Go (whatsmeow).

Evolution Go (https://github.com/evolution-foundation/evolution-go) roda como
serviço separado no docker-compose (porta 8080). Este middleware é o cliente
REST tipado consumido pelos agentes (OpenClaw e Hermes) — só ENVIO + gestão de
instância/pareamento. Inbound (receber mensagens/mídia) é coberto pelo
whatsapp_bridge.py (webhook do Evolution → bridge → agente → resposta).

Modelo de auth do Evolution Go (confirmado em pkg/middleware/auth_middleware.go):
  - Admin (criar/listar/deletar instância): header `apikey: <GLOBAL_API_KEY>`.
  - Instância (connect/qr/status e /send/*): header `apikey: <token da instância>`,
    resolvido por GetInstanceByToken. O token é DEFINIDO no /instance/create.

Env:
  EVOLUTION_BASE_URL        base da API (default http://evolution-go:8080, DNS do compose)
  EVOLUTION_API_KEY         GLOBAL_API_KEY (admin/create)
  EVOLUTION_INSTANCE_TOKEN  token da instância (send/qr/status); definido no create
  EVOLUTION_INSTANCE        nome da instância (default 'vibestack')
"""
import json
import os
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("whatsapp-evolution")

BASE_URL = os.environ.get("EVOLUTION_BASE_URL", "http://evolution-go:8080").rstrip("/")
GLOBAL_KEY = os.environ.get("EVOLUTION_API_KEY", "")
INSTANCE_TOKEN = os.environ.get("EVOLUTION_INSTANCE_TOKEN", "")
INSTANCE_NAME = os.environ.get("EVOLUTION_INSTANCE", "vibestack")


def _req(method: str, path: str, body: dict | None = None, admin: bool = False) -> Any:
    """Chama a API do Evolution Go. admin=True usa a GLOBAL key; senão o token da instância.

    Retorna o JSON parseado, ou um dict {"error", ...} em falha (mesma convenção
    do meta_ads_cli_mcp.py — nunca levanta, devolve erro estruturado pro agente).
    """
    key = GLOBAL_KEY if admin else INSTANCE_TOKEN
    if not key:
        which = "EVOLUTION_API_KEY" if admin else "EVOLUTION_INSTANCE_TOKEN"
        return {"error": f"{which} não configurado no env"}

    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"apikey": key}
    if data is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_body = {"raw": str(e)}
        hint = ""
        if e.code == 503:
            hint = " (Evolution Go sem licença ativa — ative em /manager/login)"
        elif e.code in (401, 403):
            hint = " (apikey inválida — confira EVOLUTION_API_KEY / EVOLUTION_INSTANCE_TOKEN)"
        return {"error": err_body, "status": e.code, "method": method, "path": path, "hint": hint}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "method": method, "path": path}


# ============================================================
# Instância / pareamento
# ============================================================

@mcp.tool()
def wa_create_instance(name: str | None = None, token: str | None = None, webhook: str | None = None) -> Any:
    """Cria a instância de WhatsApp no Evolution Go (admin). Idempotente do ponto
    de vista do agente: se já existir, a API retorna erro — basta seguir pro pareamento.

    name: nome da instância (default = EVOLUTION_INSTANCE).
    token: token de auth da instância (default = EVOLUTION_INSTANCE_TOKEN). É essa
           a chave usada depois em send/qr/status.
    webhook: URL opcional pra eventos inbound (fora do escopo atual; deixe vazio).
    """
    body: dict[str, Any] = {
        "name": name or INSTANCE_NAME,
        "token": token or INSTANCE_TOKEN,
    }
    if webhook:
        body["webhook"] = webhook
    return _req("POST", "/instance/create", body=body, admin=True)


@mcp.tool()
def wa_connect() -> Any:
    """Conecta/inicia a sessão da instância (após criar). Pode disparar o QR."""
    return _req("POST", "/instance/connect", body={})


@mcp.tool()
def wa_get_qr() -> Any:
    """Retorna o QR code pra parear o WhatsApp (escaneie no celular: Aparelhos conectados)."""
    return _req("GET", "/instance/qr")


@mcp.tool()
def wa_instance_status() -> Any:
    """Status da instância (connected / connecting / disconnected)."""
    return _req("GET", "/instance/status")


# ============================================================
# Envio
# ============================================================

@mcp.tool()
def wa_send_text(number: str, text: str, delay_ms: int | None = None) -> Any:
    """Envia mensagem de texto.

    number: número com código do país, só dígitos (ex: '5511999999999').
    text: conteúdo da mensagem.
    delay_ms: atraso opcional antes do envio (simula digitação), em ms.
    """
    body: dict[str, Any] = {"number": number, "text": text}
    if delay_ms is not None:
        body["delay"] = delay_ms
    return _req("POST", "/send/text", body=body)


@mcp.tool()
def wa_send_link(number: str, text: str, delay_ms: int | None = None) -> Any:
    """Envia texto com preview de link (a URL deve estar dentro de `text`)."""
    body: dict[str, Any] = {"number": number, "text": text}
    if delay_ms is not None:
        body["delay"] = delay_ms
    return _req("POST", "/send/link", body=body)


@mcp.tool()
def wa_send_media(
    number: str,
    media: str,
    mediatype: str = "image",
    caption: str | None = None,
    filename: str | None = None,
    delay_ms: int | None = None,
) -> Any:
    """Envia mídia (imagem/vídeo/áudio/documento).

    media: URL pública OU string base64 da mídia.
    mediatype: image | video | audio | document.
    caption: legenda opcional.
    filename: nome do arquivo (recomendado pra document).
    Obs: armazenamento MinIO/S3 do Evolution não é usado aqui — passe URL/base64.
    """
    body: dict[str, Any] = {"number": number, "media": media, "mediatype": mediatype}
    if caption is not None:
        body["caption"] = caption
    if filename is not None:
        body["fileName"] = filename
    if delay_ms is not None:
        body["delay"] = delay_ms
    return _req("POST", "/send/media", body=body)


if __name__ == "__main__":
    mcp.run()
