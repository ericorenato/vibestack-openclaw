#!/usr/bin/env python3
"""Bridge inbound do WhatsApp: Evolution Go (webhook) -> agente Hermes -> resposta.

Fecha o ciclo do "canal" de WhatsApp (o envio já é coberto pelo MCP
whatsapp_evolution_mcp.py). Fluxo:

  WhatsApp -> Evolution Go (evento "Message") --webhook POST--> ESTE bridge
           -> Hermes api_server (/v1/chat/completions, sessão por número)
           -> Evolution Go (/send/text) -> WhatsApp

Roda como processo no container openclaw-vibestack (subido pelo entrypoint),
escutando em 0.0.0.0:WA_BRIDGE_PORT — alcançável pelo evolution-go via DNS do
compose (http://openclaw-vibestack:<porta>/webhook). Só stdlib (http.server +
urllib), sem dependência nova.

Formato do webhook (confirmado em pkg/whatsmeow/service/whatsmeow.go):
  {"event": "Message", "data": {"Info": {"Chat","Sender","IsFromMe","ID",...},
                                "Message": {"conversation": "..." | "extendedTextMessage": {"text": "..."}}}}

Env:
  WA_BRIDGE_PORT            porta do listener (default 8765; só rede interna do compose)
  WA_BRIDGE_UPSTREAM        base do agente (default http://127.0.0.1:8642 = Hermes api_server)
  WA_BRIDGE_UPSTREAM_KEY    Bearer do api_server (= HERMES_API_SERVER_KEY)
  WA_BRIDGE_MODEL           modelo exposto (default 'hermes-agent')
  WA_BRIDGE_SESSION_PREFIX  prefixo da sessão por contato (default 'wa')
  WA_BRIDGE_ALLOWED_NUMBERS CSV de números permitidos (vazio = todos; recomendado preencher)
  WA_BRIDGE_UPSTREAM_TIMEOUT timeout (s) da chamada ao agente (default 300 — tool calls demoram)
  EVOLUTION_BASE_URL        base do Evolution Go (default http://evolution-go:8080)
  EVOLUTION_INSTANCE_TOKEN  token da instância (apikey de envio)
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Qual agente responde o canal: "hermes" (HTTP api_server) ou "openclaw" (CLI).
AGENT = os.environ.get("WA_BRIDGE_AGENT", "hermes").strip().lower()
PORT = int(os.environ.get("WA_BRIDGE_PORT", "8765"))
UPSTREAM = os.environ.get("WA_BRIDGE_UPSTREAM", "http://127.0.0.1:8642").rstrip("/")
UPSTREAM_KEY = os.environ.get("WA_BRIDGE_UPSTREAM_KEY", "")
MODEL = os.environ.get("WA_BRIDGE_MODEL", "hermes-agent")
SESSION_PREFIX = os.environ.get("WA_BRIDGE_SESSION_PREFIX", "wa")
UPSTREAM_TIMEOUT = int(os.environ.get("WA_BRIDGE_UPSTREAM_TIMEOUT", "300"))
# OpenClaw: agente especifico (binding) opcional pra rota desse canal.
OPENCLAW_AGENT_ID = os.environ.get("WA_BRIDGE_OPENCLAW_AGENT", "").strip()
EVOLUTION_BASE_URL = os.environ.get("EVOLUTION_BASE_URL", "http://evolution-go:8080").rstrip("/")
EVOLUTION_INSTANCE_TOKEN = os.environ.get("EVOLUTION_INSTANCE_TOKEN", "")
# Provisionamento idempotente da instancia (no boot do bridge):
EVOLUTION_API_KEY = os.environ.get("EVOLUTION_API_KEY", "")          # GLOBAL (admin): criar/listar instancia
EVOLUTION_INSTANCE = os.environ.get("EVOLUTION_INSTANCE", "vibestack")  # nome da instancia
# URL do webhook que o Evolution deve chamar = este bridge (DNS do compose).
PUBLIC_WEBHOOK_URL = os.environ.get("WA_BRIDGE_PUBLIC_URL", f"http://openclaw-vibestack:{PORT}/webhook")
# Proxy opcional da instancia (Static Residential do Webshare etc.). Vazio = sem proxy.
PROXY = {
    "protocol": os.environ.get("EVOLUTION_PROXY_PROTOCOL", "http"),
    "host": os.environ.get("EVOLUTION_PROXY_HOST", ""),
    "port": os.environ.get("EVOLUTION_PROXY_PORT", ""),
    "username": os.environ.get("EVOLUTION_PROXY_USERNAME", ""),
    "password": os.environ.get("EVOLUTION_PROXY_PASSWORD", ""),
}
PROXY_OK = all(PROXY[k] for k in ("host", "port", "username", "password"))

_allowed_raw = os.environ.get("WA_BRIDGE_ALLOWED_NUMBERS", "").strip()


def _br_variants(num: str) -> set:
    """Para celular BR, retorna {com_9, sem_9}. Resolve o 9o digito que o WhatsApp
    as vezes omite no JID (ex.: 5584996306412 chega como 558496306412)."""
    n = re.sub(r"\D", "", num or "")
    out = {n} if n else set()
    if n.startswith("55"):
        ddd, rest = n[2:4], n[4:]
        if len(rest) == 9 and rest.startswith("9"):
            out.add("55" + ddd + rest[1:])      # tira o 9
        elif len(rest) == 8:
            out.add("55" + ddd + "9" + rest)     # poe o 9
    return out


# Allowlist expandida com as variantes BR (com/sem 9) — match nas duas formas.
ALLOWED: set = set()
for _n in _allowed_raw.split(","):
    ALLOWED |= _br_variants(_n.strip())

# Comandos (vindos do WhatsApp) que reiniciam a conversa.
RESET_CMDS = {"/reset", "/novo", "/new", "/clear", "/limpar", "/reiniciar"}

# Dedup de message IDs já processados (Evolution pode reentregar). Bounded.
_seen_ids: dict[str, None] = {}
_seen_lock = threading.Lock()
_SEEN_MAX = 2000

# Epoch por numero: incrementa a cada /reset -> muda a sessao -> contexto novo.
_epoch: dict = {}
_epoch_lock = threading.Lock()


def _session_key(number: str) -> str:
    e = _epoch.get(number, 0)
    base = f"{SESSION_PREFIX}:{number}"
    return base if e == 0 else f"{base}:{e}"


def _reset_session(number: str) -> None:
    with _epoch_lock:
        _epoch[number] = _epoch.get(number, 0) + 1


def _log(msg: str) -> None:
    print(f"[wa-bridge] {msg}", flush=True)


def _seen(msg_id: str) -> bool:
    """True se msg_id já foi visto (e registra). Evita processar reentregas."""
    if not msg_id:
        return False
    with _seen_lock:
        if msg_id in _seen_ids:
            return True
        _seen_ids[msg_id] = None
        if len(_seen_ids) > _SEEN_MAX:
            for k in list(_seen_ids)[: _SEEN_MAX // 2]:
                _seen_ids.pop(k, None)
    return False


def _digits(jid: str) -> str:
    """Extrai o número (só dígitos) de um JID '5511...@s.whatsapp.net' ou '...:device@...'."""
    head = re.split(r"[:@]", str(jid or ""), 1)[0]
    return re.sub(r"\D", "", head)


def _extract(data: dict) -> tuple[str, str, str] | None:
    """Devolve (number, text, msg_id) de um evento Message inbound; None se deve ignorar.

    Defensivo quanto a casing (Info/info, IsFromMe/isFromMe, Message/message).
    """
    info = data.get("Info") or data.get("info") or {}
    msg = data.get("Message") or data.get("message") or {}

    from_me = info.get("IsFromMe", info.get("isFromMe", info.get("fromMe", False)))
    if from_me:
        return None  # mensagem nossa (eco do envio)

    chat = str(info.get("Chat") or info.get("chat") or "")
    if "@g.us" in chat or "@broadcast" in chat or "status@" in chat:
        return None  # grupos e status: fora do canal 1:1

    sender = info.get("Sender") or info.get("sender") or chat
    number = _digits(sender)
    if not number:
        return None

    text = msg.get("conversation") or msg.get("Conversation")
    if not text:
        ext = msg.get("extendedTextMessage") or msg.get("ExtendedTextMessage") or {}
        text = ext.get("text") or ext.get("Text")
    if not text:
        # mídia/áudio/etc. sem texto — fora do escopo (só texto por enquanto)
        return None

    msg_id = str(info.get("ID") or info.get("Id") or info.get("id") or "")
    return number, str(text), msg_id


def _ask_hermes(number: str, text: str) -> str:
    """Hermes: HTTP /v1/chat/completions, sessão por contato (X-Hermes-Session-Id)."""
    if not UPSTREAM_KEY:
        return "(bridge sem WA_BRIDGE_UPSTREAM_KEY configurada)"
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": text}],
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{UPSTREAM}/v1/chat/completions",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {UPSTREAM_KEY}",
            "X-Hermes-Session-Id": _session_key(number),
        },
    )
    with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    try:
        return out["choices"][0]["message"]["content"] or "(resposta vazia)"
    except (KeyError, IndexError, TypeError):
        return "(nao consegui interpretar a resposta do Hermes)"


def _ask_openclaw(number: str, text: str) -> str:
    """OpenClaw: one-shot `openclaw agent --message ... --to +<num> --json`.

    --to deriva a sessão pelo número (continuidade por contato). SEM --deliver:
    o OpenClaw só DEVOLVE a resposta (a gente envia pelo Evolution). --json dá
    saída estruturada; parseamos o texto da resposta de forma defensiva.
    """
    cmd = ["openclaw", "agent", "--message", text, "--session-key", _session_key(number), "--json"]
    if OPENCLAW_AGENT_ID:
        cmd += ["--agent", OPENCLAW_AGENT_ID]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=UPSTREAM_TIMEOUT, check=False)
    if r.returncode != 0:
        return f"(openclaw agent falhou: {(r.stderr or r.stdout).strip()[:200]})"
    out_raw = r.stdout.strip()
    try:
        out = json.loads(out_raw)
    except json.JSONDecodeError:
        return out_raw or "(resposta vazia do openclaw)"
    # Procura o texto da resposta em chaves comuns do --json.
    for k in ("reply", "text", "message", "content", "response", "output", "finalText"):
        v = out.get(k) if isinstance(out, dict) else None
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, dict):
            for kk in ("text", "content", "message"):
                vv = v.get(kk)
                if isinstance(vv, str) and vv.strip():
                    return vv
    return out_raw or "(nao consegui interpretar a resposta do openclaw)"


def _ask_agent(number: str, text: str) -> str:
    """Despacha pro agente configurado (WA_BRIDGE_AGENT)."""
    if AGENT == "openclaw":
        return _ask_openclaw(number, text)
    return _ask_hermes(number, text)


def _send_whatsapp(number: str, text: str) -> None:
    """Envia a resposta de volta pelo Evolution Go (/send/text)."""
    body = json.dumps({"number": number, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{EVOLUTION_BASE_URL}/send/text",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "apikey": EVOLUTION_INSTANCE_TOKEN},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        resp.read()


def _reply_safe(number: str, text: str) -> None:
    """Envia uma resposta direta (ex.: confirmacao de reset) tolerando erro."""
    try:
        _send_whatsapp(number, text)
    except Exception as e:  # noqa: BLE001
        _log(f"erro enviando aviso pra {number}: {e}")


def _process(number: str, text: str) -> None:
    """Worker: pergunta ao agente e responde no WhatsApp. Roda fora do request HTTP."""
    try:
        _log(f"in  <- {number}: {text[:80]!r}")
        reply = _ask_agent(number, text)
        _send_whatsapp(number, reply)
        _log(f"out -> {number}: {reply[:80]!r}")
    except urllib.error.HTTPError as e:
        _log(f"ERRO HTTP {e.code} processando {number}: {e.read()[:200]!r}")
    except Exception as e:  # noqa: BLE001
        _log(f"ERRO processando {number}: {e}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silencia o log padrao ruidoso do http.server
        pass

    def _ok(self, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self):
        # Health check simples.
        self._ok()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        # Responde 200 IMEDIATAMENTE — o agente pode demorar (tool calls);
        # assim o Evolution nao expira/reentrega o webhook.
        self._ok()
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return
        if str(payload.get("event") or payload.get("Event") or "").lower() != "message":
            return
        data = payload.get("data") or payload.get("Data") or {}
        extracted = _extract(data)
        if not extracted:
            return
        number, text, msg_id = extracted
        if _seen(msg_id):
            return
        # Allowlist com variantes BR (com/sem 9) — casa nas duas formas.
        if ALLOWED and not (_br_variants(number) & ALLOWED):
            _log(f"ignorado (fora da allowlist): {number}")
            return
        # Comando de reset vindo do WhatsApp -> nova sessao, sem chamar o agente.
        if text.strip().lower() in RESET_CMDS:
            _reset_session(number)
            _log(f"reset solicitado por {number} -> sessao {_session_key(number)}")
            threading.Thread(
                target=_reply_safe,
                args=(number, "🔄 Conversa reiniciada. Pode mandar a próxima mensagem."),
                daemon=True,
            ).start()
            return
        threading.Thread(target=_process, args=(number, text), daemon=True).start()


def _evo_request(method: str, path: str, body: dict | None = None, admin: bool = False) -> tuple[int, object]:
    """Request ao Evolution Go. admin=True usa a GLOBAL key; senao o token da instancia.
    Levanta urllib.error.HTTPError em erro (tratado por quem chama)."""
    key = EVOLUTION_API_KEY if admin else EVOLUTION_INSTANCE_TOKEN
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"apikey": key}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{EVOLUTION_BASE_URL}{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return resp.status, (json.loads(raw) if raw else {})


def _get_instance() -> dict | None:
    """Retorna o dict da instancia (por nome) — com id/proxy/connected — ou None."""
    _, out = _evo_request("GET", "/instance/all", admin=True)
    items = out.get("data") if isinstance(out, dict) else out
    if not isinstance(items, list):
        return None
    for i in items:
        if isinstance(i, dict) and i.get("name") == EVOLUTION_INSTANCE:
            return i
    return None


def _proxy_struct() -> dict:
    """Corpo do proxy (SetProxyStruct / ProxyConfig) a partir do env."""
    return {k: PROXY[k] for k in ("protocol", "host", "port", "username", "password")}


def _provision() -> None:
    """Garante a instancia (idempotente): cria so se faltar, com webhook+token+proxy,
    conecta e reporta status. Roda em background com retry (espera evolution-go/licenca).

    Tira a criacao de instancia do agente: o canal nasce certo no boot e o agente
    so' USA (envia via MCP, recebe via webhook). Nunca recria uma instancia existente.
    """
    if not EVOLUTION_API_KEY:
        _log("provisionamento pulado: EVOLUTION_API_KEY (global) ausente — defina pra criar a instancia automaticamente.")
        return
    for attempt in range(1, 31):
        try:
            inst = _get_instance()
            if inst is None:
                # O CreateStruct do Evolution NAO aceita 'webhook' (so name/token/proxy);
                # o webhook e' definido no connect (webhookUrl). O proxy SIM vai no create.
                body: dict = {"name": EVOLUTION_INSTANCE, "token": EVOLUTION_INSTANCE_TOKEN}
                if PROXY_OK:
                    body["proxy"] = _proxy_struct()
                _evo_request("POST", "/instance/create", body=body, admin=True)
                _log(f"instancia '{EVOLUTION_INSTANCE}' criada (proxy={'sim' if PROXY_OK else 'nao'}).")
            else:
                _log(f"instancia '{EVOLUTION_INSTANCE}' ja existe — reaproveitando (nao recrio).")
                # Aplica o proxy numa instancia que ainda nao tem (edita via POST /instance/proxy/<id>).
                if PROXY_OK and not str(inst.get("proxy") or "").strip():
                    iid = inst.get("id")
                    if iid:
                        try:
                            _evo_request("POST", f"/instance/proxy/{iid}", body=_proxy_struct(), admin=True)
                            _log(f"proxy aplicado na instancia existente (host={PROXY['host']}). Reconectando p/ valer...")
                            try:
                                _evo_request("POST", "/instance/reconnect", body={})
                            except urllib.error.HTTPError:
                                pass
                        except urllib.error.HTTPError as e:
                            _log(f"falha ao aplicar proxy (HTTP {e.code}): {e.read()[:120]!r}")
            # webhook + eventos no CONNECT (idempotente — reaplica mesmo se a instancia ja existia).
            try:
                _evo_request("POST", "/instance/connect",
                             body={"webhookUrl": PUBLIC_WEBHOOK_URL, "subscribe": ["MESSAGE"]})
                _log(f"connect ok — webhook={PUBLIC_WEBHOOK_URL}, eventos=[MESSAGE], proxy={'sim' if PROXY_OK else 'nao'}.")
            except urllib.error.HTTPError as e:
                _log(f"connect HTTP {e.code} (ok se ja conectado): {e.read()[:120]!r}")
            try:
                _, st = _evo_request("GET", "/instance/status")
                _log(f"status da instancia: {st}")
            except urllib.error.HTTPError:
                pass
            _log(f"provisionamento ok. Se nao estiver 'connected', pareie o QR no Manager: http://127.0.0.1:8080/manager.")
            return
        except urllib.error.HTTPError as e:
            if e.code == 503:
                _log(f"Evolution sem LICENCA ativa (503). Ative no Manager e reinicie o container. (tentativa {attempt})")
                return
            _log(f"provisionamento: HTTP {e.code} — {e.read()[:160]!r} (tentativa {attempt})")
        except Exception as e:  # noqa: BLE001 — connectivity: evolution-go pode nao estar pronto
            _log(f"aguardando evolution-go... ({e}) (tentativa {attempt})")
        time.sleep(10)
    _log("provisionamento desistiu — crie a instancia manualmente (wa_create_instance) ou reinicie depois de ativar a licenca.")


def main() -> None:
    if not EVOLUTION_INSTANCE_TOKEN:
        _log("AVISO: EVOLUTION_INSTANCE_TOKEN vazio — nao vou conseguir responder no WhatsApp.")
    if not ALLOWED:
        _log("AVISO: WA_BRIDGE_ALLOWED_NUMBERS vazio — QUALQUER numero que mandar msg fala com o agente.")
    # Provisiona a instancia em background (nao bloqueia o servidor de webhook).
    threading.Thread(target=_provision, daemon=True).start()
    dest = f"openclaw CLI (agent={OPENCLAW_AGENT_ID or 'default'})" if AGENT == "openclaw" else f"hermes {UPSTREAM}"
    _log(f"escutando em 0.0.0.0:{PORT} (webhook POST /webhook) -> {dest} -> resposta via {EVOLUTION_BASE_URL}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
