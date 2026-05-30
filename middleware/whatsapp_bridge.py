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

Mídia inbound (imagem/áudio): além de texto, o bridge processa imagem e áudio.
Baixa os bytes na ordem mediaUrl (S3/MinIO presigned) -> base64 inline ->
POST /message/downloadmedia (funciona sem S3), salva em _shared/assets/wa/ e
manda pro modelo (Hermes multimodal: image_url/input_audio; OpenClaw: via arquivo).
Se o modelo configurado não aceitar a modalidade, responde avisando que não
comporta. Configure o storage do Evolution (MINIO_*/Backblaze) p/ usar mediaUrl.

Formato do webhook (confirmado em pkg/whatsmeow/service/whatsmeow.go):
  {"event": "Message", "data": {"Info": {"Chat","Sender","IsFromMe","ID",...},
     "Message": {"conversation": "..." | "extendedTextMessage": {"text": "..."}
                 | "imageMessage"|"audioMessage"|... {"caption","mimetype",...},
                 "mediaUrl": "...(S3)", "base64": "...(sem S3)", "mimetype": "..."}}}

Env:
  WA_BRIDGE_PORT            porta do listener (default 8765; só rede interna do compose)
  WA_BRIDGE_UPSTREAM        base do agente (default http://127.0.0.1:8642 = Hermes api_server)
  WA_BRIDGE_UPSTREAM_KEY    Bearer do api_server (= HERMES_API_SERVER_KEY)
  WA_BRIDGE_MODEL           modelo exposto (default 'hermes-agent')
  WA_BRIDGE_SESSION_PREFIX  prefixo da sessão por contato (default 'wa')
  WA_BRIDGE_ALLOWED_NUMBERS CSV de números permitidos (vazio = todos; recomendado preencher)
  WA_BRIDGE_UPSTREAM_TIMEOUT timeout (s) da chamada ao agente (default 0 = ILIMITADO; localhost)
  EVOLUTION_BASE_URL        base do Evolution Go (default http://evolution-go:8080)
  EVOLUTION_INSTANCE_TOKEN  token da instância (apikey de envio)
"""
import base64
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
# Timeout da chamada ao agente. 0 = ILIMITADO (default) — o agente roda quanto
# precisar e a resposta sai quando terminar. A chamada e' localhost (mesmo
# container), entao segurar a conexao e' seguro; o bridge ja' respondeu 200 ao
# webhook e processa em thread, sem nada esperando do outro lado.
UPSTREAM_TIMEOUT = int(os.environ.get("WA_BRIDGE_UPSTREAM_TIMEOUT", "0"))
_TIMEOUT = UPSTREAM_TIMEOUT if UPSTREAM_TIMEOUT > 0 else None
ACK_AFTER = int(os.environ.get("WA_BRIDGE_ACK_AFTER", "20"))  # avisa "processando" se passar disso (0 = off)
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

# Configuracoes da instancia na criacao: por padrao ignora grupos e status
# (canal 1:1 com clientes). Mude no Manager do Evolution se quiser grupos.
def _envbool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes"}

IGNORE_GROUPS = _envbool("EVOLUTION_IGNORE_GROUPS", True)
IGNORE_STATUS = _envbool("EVOLUTION_IGNORE_STATUS", True)

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

# --- Mídia inbound (imagem/áudio) ------------------------------------------
# Diretório persistente onde a mídia recebida é salva (dentro do volume do OpenClaw).
WA_MEDIA_DIR = "/root/.openclaw/workspace/_shared/assets/wa"

# Containers de mídia no data.Message (protojson lowerCamelCase) -> tipo lógico.
# Confirmado em evolution-go pkg/whatsmeow/service/whatsmeow.go.
_MEDIA_CONTAINERS = {
    "imagemessage": "image",
    "stickermessage": "image",
    "audiomessage": "audio",
    "videomessage": "video",
    "documentmessage": "document",
}
_MIME_EXT = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
    "image/webp": "webp", "image/gif": "gif",
    "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mp4": "m4a",
    "audio/aac": "aac", "audio/wav": "wav", "audio/x-wav": "wav", "audio/amr": "amr",
    "video/mp4": "mp4", "video/3gpp": "3gp",
    "application/pdf": "pdf",
}


class ModelMediaUnsupported(Exception):
    """O modelo/endpoint do agente não aceita a mídia enviada (imagem/áudio)."""

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


def _find_media(msg: dict) -> tuple[str, dict] | None:
    """Acha o container de mídia em data.Message. Retorna (kind, obj) ou None."""
    lower = {k.lower(): k for k in msg.keys()}
    for lk, kind in _MEDIA_CONTAINERS.items():
        real = lower.get(lk)
        if real:
            obj = msg.get(real)
            if isinstance(obj, dict):
                return kind, obj
    return None


def _extract(data: dict) -> dict | None:
    """Devolve {number, text, msg_id, media} de um evento Message inbound; None se ignorar.

    media=None para texto puro. Para imagem/áudio/vídeo/documento, media é um dict
    com kind/caption/mimetype/media_url/base64/message (o data.Message cru, usado
    pelo /message/downloadmedia). text recebe a legenda da mídia (pode ser vazia).
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

    msg_id = str(info.get("ID") or info.get("Id") or info.get("id") or "")

    text = msg.get("conversation") or msg.get("Conversation")
    if not text:
        ext = msg.get("extendedTextMessage") or msg.get("ExtendedTextMessage") or {}
        text = ext.get("text") or ext.get("Text")

    media = None
    if not text:
        found = _find_media(msg)
        if not found:
            return None  # sem texto e sem mídia conhecida (reação, location, etc.)
        kind, obj = found
        caption = obj.get("caption") or obj.get("Caption") or ""
        media = {
            "kind": kind,
            "caption": str(caption or ""),
            # mimetype/mediaUrl/base64 são irmãos que o Evolution injeta em data.Message.
            "mimetype": str(msg.get("mimetype") or msg.get("mimeType") or obj.get("mimetype") or ""),
            "media_url": msg.get("mediaUrl") or msg.get("mediaURL") or msg.get("MediaUrl"),
            "base64": msg.get("base64") or msg.get("Base64"),
            "message": msg,
            "msg_id": msg_id,
        }
        text = str(caption or "")

    return {"number": number, "text": str(text), "msg_id": msg_id, "media": media}


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
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
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
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT, check=False)
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
    """Worker: pergunta ao agente e responde no WhatsApp. Roda fora do request HTTP.

    Tarefas longas (gerar criativo etc.) podem levar minutos: avisamos "processando"
    se passar de ACK_AFTER, e em erro/timeout mandamos um aviso (em vez de silencio).
    """
    _log(f"in  <- {number}: {text[:80]!r}")
    done = threading.Event()

    def _ack_if_slow() -> None:
        if ACK_AFTER > 0 and not done.wait(ACK_AFTER):
            _reply_safe(number, "🛠️ Tô processando — tarefas maiores levam alguns minutos. Já te respondo.")

    threading.Thread(target=_ack_if_slow, daemon=True).start()
    try:
        reply = _ask_agent(number, text)
        done.set()
        _send_whatsapp(number, reply)
        _log(f"out -> {number}: {reply[:80]!r}")
    except urllib.error.HTTPError as e:
        done.set()
        _log(f"ERRO HTTP {e.code} processando {number}: {e.read()[:200]!r}")
        _reply_safe(number, "⚠️ Deu um erro ao processar. Pode tentar de novo?")
    except Exception as e:  # noqa: BLE001
        done.set()
        _log(f"ERRO processando {number}: {e}")
        msg = ("⏳ A operação demorou mais que o limite e foi interrompida. "
               "Tente dividir em passos menores, ou repita o pedido.") if "timed out" in str(e).lower() \
              else "⚠️ Não consegui concluir agora. Pode tentar de novo?"
        _reply_safe(number, msg)


# ============================================================
# Mídia inbound: download (S3/MinIO presigned, base64 inline, ou /downloadmedia)
# + envio ao modelo (Hermes multimodal / OpenClaw via arquivo salvo).
# ============================================================

def _http_get_bytes(url: str) -> bytes:
    """GET cru de uma URL (ex.: presigned do MinIO/Backblaze)."""
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "wa-bridge"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _download_via_evolution(message: dict) -> tuple[bytes, str]:
    """Baixa+descriptografa a mídia via POST /message/downloadmedia (funciona SEM S3).

    Body = {"message": <data.Message>}; auth = apikey da instância. A resposta traz
    data.base64 como data-URL ('data:<mime>;base64,...'). Retorna (bytes, mimetype).
    """
    body = json.dumps({"message": message}).encode("utf-8")
    req = urllib.request.Request(
        f"{EVOLUTION_BASE_URL}/message/downloadmedia",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "apikey": EVOLUTION_INSTANCE_TOKEN},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    durl = ""
    if isinstance(out, dict):
        durl = (out.get("data") or {}).get("base64") or out.get("base64") or ""
    if isinstance(durl, str) and durl.startswith("data:") and "," in durl:
        head, b64 = durl.split(",", 1)
        mime = head[5:].split(";")[0]
        return base64.b64decode(b64), mime
    raise RuntimeError("downloadmedia não devolveu base64")


def _fetch_media_bytes(media: dict) -> tuple[bytes, str]:
    """Obtém os bytes da mídia. Prioridade: mediaUrl (S3/MinIO) -> base64 inline -> /downloadmedia."""
    mime = (media.get("mimetype") or "").strip()
    url = media.get("media_url")
    if url:
        return _http_get_bytes(url), mime
    b64 = media.get("base64")
    if b64:
        return base64.b64decode(b64), mime
    return _download_via_evolution(media.get("message") or {})


def _save_media(number: str, media: dict, data_bytes: bytes, mime: str) -> str:
    """Salva a mídia em WA_MEDIA_DIR (persistente, dentro do volume) e devolve o path."""
    ext = _MIME_EXT.get((mime or "").split(";")[0].strip().lower(), "bin")
    stamp = re.sub(r"\W", "", media.get("msg_id") or "") or str(int(time.time()))
    try:
        os.makedirs(WA_MEDIA_DIR, exist_ok=True)
    except OSError:
        pass
    path = f"{WA_MEDIA_DIR}/{number}-{stamp}.{ext}"
    with open(path, "wb") as f:
        f.write(data_bytes)
    return path


def _audio_format(mime: str) -> str:
    """Formato p/ o content part input_audio do chat-completions."""
    m = (mime or "").split(";")[0].strip().lower()
    return {
        "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp3": "mp3",
        "audio/mp4": "m4a", "audio/aac": "aac",
        "audio/wav": "wav", "audio/x-wav": "wav", "audio/amr": "amr",
    }.get(m, "ogg")


def _ask_hermes_media(number: str, kind: str, data_bytes: bytes, mime: str, caption: str) -> str:
    """Hermes multimodal via /v1/chat/completions (content image_url / input_audio).

    Levanta ModelMediaUnsupported em 4xx do upstream (modelo/endpoint não aceita a
    modalidade) ou resposta vazia/erro — o caller manda o aviso de "não comporta".
    """
    if not UPSTREAM_KEY:
        return "(bridge sem WA_BRIDGE_UPSTREAM_KEY configurada)"
    b64 = base64.b64encode(data_bytes).decode("ascii")
    prompt = caption.strip() or (
        "Descreva e responda sobre esta imagem." if kind == "image"
        else "Transcreva e responda a este áudio."
    )
    if kind == "image":
        part = {"type": "image_url", "image_url": {"url": f"data:{mime or 'image/jpeg'};base64,{b64}"}}
    else:
        part = {"type": "input_audio", "input_audio": {"data": b64, "format": _audio_format(mime)}}
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, part]}],
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{UPSTREAM}/v1/chat/completions", data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {UPSTREAM_KEY}",
            "X-Hermes-Session-Id": _session_key(number),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:  # noqa: BLE001
            pass
        if 400 <= e.code < 500:
            # 4xx num envio multimodal = modelo/endpoint não suporta a modalidade.
            raise ModelMediaUnsupported(f"HTTP {e.code}: {detail}")
        raise
    if isinstance(out, dict) and out.get("error"):
        raise ModelMediaUnsupported(str(out.get("error")))
    try:
        content = out["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        content = None
    if not content:
        raise ModelMediaUnsupported("resposta vazia do modelo")
    return content


def _ask_openclaw_media(number: str, kind: str, caption: str, path: str) -> str:
    """OpenClaw: passa o arquivo salvo + legenda no prompt (o agente decide se interpreta)."""
    desc = "imagem" if kind == "image" else "áudio"
    msg = f"[O usuário enviou um(a) {desc} pelo WhatsApp, salvo em {path}."
    if caption:
        msg += f" Legenda: {caption}."
    msg += " Interprete com suas ferramentas se possível; senão, peça os detalhes por texto.]"
    return _ask_openclaw(number, msg)


def _process_media(number: str, media: dict) -> None:
    """Worker para mensagens de mídia: baixa, salva em _shared/assets/wa e manda pro agente."""
    kind = media["kind"]
    caption = media.get("caption") or ""
    _log(f"in  <- {number}: [{kind}] caption={caption[:60]!r}")
    done = threading.Event()

    def _ack_if_slow() -> None:
        if ACK_AFTER > 0 and not done.wait(ACK_AFTER):
            _reply_safe(number, "🛠️ Recebi sua mídia, tô processando — já te respondo.")

    threading.Thread(target=_ack_if_slow, daemon=True).start()

    # Só imagem e áudio são interpretados pelo modelo. Vídeo/documento: aviso amigável.
    if kind not in ("image", "audio"):
        done.set()
        _reply_safe(number, "Recebi seu arquivo, mas por ora só interpreto *imagem* e *áudio*. Pode mandar por texto?")
        return

    try:
        data_bytes, mime = _fetch_media_bytes(media)
        path = _save_media(number, media, data_bytes, mime)
        _log(f"     media salva: {path} ({len(data_bytes)} bytes, {mime or '?'})")
        if AGENT == "openclaw":
            reply = _ask_openclaw_media(number, kind, caption, path)
        else:
            reply = _ask_hermes_media(number, kind, data_bytes, mime, caption)
        done.set()
        _send_whatsapp(number, reply)
        _log(f"out -> {number}: {reply[:80]!r}")
    except ModelMediaUnsupported as e:
        done.set()
        _log(f"modelo nao comporta {kind} p/ {number}: {e}")
        tipo = "imagens" if kind == "image" else "áudios"
        _reply_safe(number, f"⚠️ O modelo configurado neste agente não interpreta {tipo}. Por favor, descreva por texto.")
    except Exception as e:  # noqa: BLE001
        done.set()
        _log(f"ERRO processando mídia de {number}: {e}")
        _reply_safe(number, "⚠️ Não consegui baixar/processar a mídia. Pode tentar de novo ou enviar por texto?")


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
        number = extracted["number"]
        text = extracted["text"]
        msg_id = extracted["msg_id"]
        media = extracted["media"]
        if _seen(msg_id):
            return
        # Allowlist com variantes BR (com/sem 9) — casa nas duas formas.
        if ALLOWED and not (_br_variants(number) & ALLOWED):
            _log(f"ignorado (fora da allowlist): {number}")
            return
        # Mídia (imagem/áudio/...): baixa e manda pro agente em worker separado.
        if media is not None:
            threading.Thread(target=_process_media, args=(number, media), daemon=True).start()
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
                body: dict = {
                    "name": EVOLUTION_INSTANCE,
                    "token": EVOLUTION_INSTANCE_TOKEN,
                    "advancedSettings": {"ignoreGroups": IGNORE_GROUPS, "ignoreStatus": IGNORE_STATUS},
                }
                if PROXY_OK:
                    body["proxy"] = _proxy_struct()
                _evo_request("POST", "/instance/create", body=body, admin=True)
                _log(f"instancia '{EVOLUTION_INSTANCE}' criada (proxy={'sim' if PROXY_OK else 'nao'}, "
                     f"ignoreGroups={IGNORE_GROUPS}, ignoreStatus={IGNORE_STATUS}).")
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
