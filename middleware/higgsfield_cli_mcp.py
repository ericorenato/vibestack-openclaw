#!/usr/bin/env python3
"""MCP server stdio que expõe o Higgsfield CLI (`higgsfield`) como tools tipados.

Voltado ao agente Criativo: geração de imagem/vídeo, soul-id (identidade
face-faithful a partir de fotos) e upload. Espelha o padrão de
middleware/meta_ads_cli_mcp.py: shell-out via subprocess, retorno SEMPRE
dict/valor (sem exception bubble) e, em falha, dict com 'error'/'cmd'/'stdout'.

Auth: o CLI guarda o token em ~/.higgsfield (login via `higgsfield auth login`,
device-code OAuth no navegador — sem API key). O container monta
/root/.higgsfield como volume, então a sessão sobrevive a restart/rebuild.
Este MCP precisa de HOME=/root no env (openclaw/hermes spawnam o child com env
reduzido) — garantido no entrypoint.sh e reforçado aqui em _env().

Persistência de mídia: arquivos baixados vão para ASSETS_DIR (dentro do volume
/root/.openclaw). NUNCA /tmp ou cwd — esses somem ao reiniciar o container.
Para storage canônico de longo prazo, suba pro Backblaze B2 com a tool
b2_upload_local do MCP media-editor.

Observação: a doc pública do CLI é enxuta; as flags dos comandos `generate`,
`upload` e `soul-id` podem variar entre versões. Os params tipados cobrem o uso
comum; para qualquer subcomando/flag fora do mapeado, use a tool `raw`.
"""
import hashlib
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("higgsfield-cli")
CLI = "higgsfield"

# Diretório persistente para a mídia gerada/baixada (dentro do volume do OpenClaw).
ASSETS_DIR = Path("/root/.openclaw/workspace/_shared/assets")
# Onde gravamos os soul-ids treinados, pra reuso entre sessões/restarts.
SOUL_IDS_FILE = ASSETS_DIR.parent / "higgsfield-soul-ids.json"

MEDIA_EXT = (
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".mp4", ".mov", ".webm", ".m4v",
    ".mp3", ".wav", ".m4a",
)
_URL_RE = re.compile(r'https?://[^\s"\'<>)\]]+')


# ============================================================
# Helpers privados
# ============================================================

def _env() -> dict[str, str]:
    """Env do subprocesso com HOME e PATH garantidos.

    HOME: o CLI lê o token de ~/.higgsfield. PATH: garante achar o binário
    'higgsfield' (/usr/local/bin) e 'node' mesmo se o MCP child herdar env enxuto.
    """
    env = dict(os.environ)
    env.setdefault("HOME", "/root")
    env["PATH"] = "/usr/local/bin:/root/.local/bin:" + env.get("PATH", "/usr/bin:/bin")
    return env


def _run(*args: str, parse_json: bool = True, timeout: int = 600) -> Any:
    """Executa `higgsfield <args>`. Retorna JSON parseado, string crua ou dict de erro.

    timeout generoso (default 600s) porque `generate --wait` espera o job render.
    """
    cmd = [CLI, *args]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, check=False,
            env=_env(), timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"timeout após {timeout}s", "cmd": " ".join(cmd)}
    except FileNotFoundError:
        return {
            "error": "CLI 'higgsfield' não encontrado no PATH",
            "cmd": " ".join(cmd),
            "hint": "A imagem instala via 'npm install -g @higgsfield/cli'. Rebuild a imagem.",
        }
    if r.returncode != 0:
        err = r.stderr.strip() or f"exit {r.returncode}"
        hint = None
        if re.search(r"auth|login|token|unauthenticated|session", err, re.I):
            hint = "Sessão expirada/ausente. Rode: docker exec -it openclaw-vibestack higgsfield auth login"
        return {"error": err, "stdout": r.stdout, "cmd": " ".join(cmd), **({"hint": hint} if hint else {})}
    out = r.stdout.strip()
    if parse_json and out:
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return out
    return out


def _ensure_assets() -> None:
    try:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _download(url: str, filename: str | None = None) -> dict[str, Any]:
    """Baixa uma URL para ASSETS_DIR (persistente). Retorna dict com path ou error."""
    _ensure_assets()
    base = filename or os.path.basename(urllib.parse.urlparse(url).path)
    if not base:
        base = hashlib.sha1(url.encode()).hexdigest()[:16]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    dest = ASSETS_DIR / base
    try:
        urllib.request.urlretrieve(url, dest)  # noqa: S310 (URL vem do próprio Higgsfield)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "error": str(e)}
    return {"url": url, "path": str(dest), "bytes": dest.stat().st_size}


def _harvest_media(result: Any) -> list[dict[str, Any]]:
    """Acha URLs de mídia no resultado do CLI e baixa pra ASSETS_DIR (best-effort)."""
    text = result if isinstance(result, str) else json.dumps(result)
    saved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for u in _URL_RE.findall(text):
        u = u.rstrip(".,);]")
        if u in seen:
            continue
        path_only = urllib.parse.urlparse(u).path.lower()
        if path_only.endswith(MEDIA_EXT):
            seen.add(u)
            saved.append(_download(u))
    return saved


# ============================================================
# Auth / conta / catálogo
# ============================================================

@mcp.tool()
def auth_status() -> Any:
    """Estado da autenticação do CLI (`higgsfield auth status`).

    Se acusar não-autenticado/expirado, o login é manual e único:
    `docker exec -it openclaw-vibestack higgsfield auth login` (abre o navegador).
    O token fica em /root/.higgsfield (volume) — sobrevive a restart/rebuild.
    """
    return _run("auth", "status")


@mcp.tool()
def list_models(kind: str | None = None) -> Any:
    """Lista o catálogo de modelos disponíveis (`higgsfield model list`).

    kind: filtro opcional passado como argumento extra (ex.: 'image', 'video'),
    caso a sua versão do CLI suporte. Se não suportar, omita.
    """
    args = ["model", "list"]
    if kind:
        args.append(kind)
    return _run(*args)


# ============================================================
# Geração
# ============================================================

@mcp.tool()
def generate_image(
    prompt: str,
    model: str = "nano_banana_2",
    soul_id: str | None = None,
    extra_args: list[str] | None = None,
    download: bool = True,
) -> Any:
    """Gera imagem (`higgsfield generate create <model> --prompt ... --wait`).

    model: ex. 'nano_banana_2' (texto->imagem). Para usar o rosto do Érico via
           soul-id, use model='text2image_soul_v2' e passe soul_id.
    soul_id: id de uma identidade treinada (ver soul_id_create / list_soul_ids).
    extra_args: flags adicionais cruas pro CLI (ex.: ['--aspect-ratio','9:16']).
    download: se True, baixa as mídias do resultado pra _shared/assets/ (persistente).

    Retorna {"result": <saída do CLI>, "saved": [<arquivos baixados>]}.
    """
    args = ["generate", "create", model, "--prompt", prompt, "--wait"]
    if soul_id:
        args += ["--soul-id", soul_id]
    if extra_args:
        args += [str(a) for a in extra_args]
    result = _run(*args)
    saved = _harvest_media(result) if download and not (isinstance(result, dict) and "error" in result) else []
    return {"result": result, "saved": saved}


@mcp.tool()
def generate_video(
    prompt: str,
    model: str = "kling3_0",
    duration: int | None = 5,
    soul_id: str | None = None,
    extra_args: list[str] | None = None,
    download: bool = True,
) -> Any:
    """Gera vídeo (`higgsfield generate create <model> --prompt ... [--duration N] --wait`).

    model: ex. 'kling3_0'. duration em segundos (None = default do modelo).
    extra_args: flags adicionais cruas pro CLI.
    download: baixa as mídias do resultado pra _shared/assets/ (persistente).

    Retorna {"result": <saída do CLI>, "saved": [<arquivos baixados>]}.
    """
    args = ["generate", "create", model, "--prompt", prompt, "--wait"]
    if duration is not None:
        args += ["--duration", str(duration)]
    if soul_id:
        args += ["--soul-id", soul_id]
    if extra_args:
        args += [str(a) for a in extra_args]
    result = _run(*args)
    saved = _harvest_media(result) if download and not (isinstance(result, dict) and "error" in result) else []
    return {"result": result, "saved": saved}


@mcp.tool()
def generate_list() -> Any:
    """Lista jobs de geração recentes (`higgsfield generate list`)."""
    return _run("generate", "list")


# ============================================================
# Soul-ID (identidade face-faithful)
# ============================================================

@mcp.tool()
def soul_id_create(name: str, images: list[str], soul2: bool = True) -> Any:
    """Treina um soul-id (identidade fiel a um rosto) a partir de 3–5 fotos.

    `higgsfield soul-id create --name <name> [--soul-2] --image f1 --image f2 ...`

    images: caminhos LOCAIS das fotos (baixe a seed do Érico do B2 primeiro, ex.:
            via media-editor, para _shared/assets/, e aponte aqui).
    soul2: usa a flag --soul-2 (versão do treino). Desligue se sua versão não tiver.

    IMPORTANTE: anote o soul_id retornado com save_soul_id(name, soul_id) para
    reusá-lo em generate_image(..., soul_id=...) sem re-treinar.
    """
    missing = [p for p in images if not Path(p).exists()]
    if missing:
        return {"error": "arquivo(s) não encontrado(s)", "missing": missing,
                "hint": "Use caminhos locais já baixados em _shared/assets/."}
    args = ["soul-id", "create", "--name", name]
    if soul2:
        args.append("--soul-2")
    for img in images:
        args += ["--image", img]
    return _run(*args, timeout=1200)


@mcp.tool()
def save_soul_id(name: str, soul_id: str, note: str | None = None) -> Any:
    """Grava {name -> soul_id} em _shared/higgsfield-soul-ids.json (persistente).

    Use depois de soul_id_create para não perder o id entre sessões/restarts.
    """
    _ensure_assets()
    data: dict[str, Any] = {}
    if SOUL_IDS_FILE.exists():
        try:
            data = json.loads(SOUL_IDS_FILE.read_text()) or {}
        except (OSError, json.JSONDecodeError):
            data = {}
    entry: dict[str, Any] = {"soul_id": soul_id}
    if note:
        entry["note"] = note
    data[name] = entry
    try:
        SOUL_IDS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except OSError as e:
        return {"error": str(e)}
    return {"saved": True, "path": str(SOUL_IDS_FILE), "name": name, "soul_id": soul_id}


@mcp.tool()
def list_soul_ids() -> Any:
    """Lista os soul-ids salvos em _shared/higgsfield-soul-ids.json."""
    if not SOUL_IDS_FILE.exists():
        return {}
    try:
        return json.loads(SOUL_IDS_FILE.read_text()) or {}
    except (OSError, json.JSONDecodeError) as e:
        return {"error": str(e), "path": str(SOUL_IDS_FILE)}


# ============================================================
# Upload / download utilitários
# ============================================================

@mcp.tool()
def upload(local_path: str) -> Any:
    """Sobe um arquivo local pro Higgsfield e devolve o UUID (`higgsfield upload <path>`).

    Use o UUID como input de generation quando o modelo aceitar imagem/vídeo de
    referência. Se sua versão do CLI usar outra sintaxe, chame via `raw`.
    """
    if not Path(local_path).exists():
        return {"error": f"arquivo não encontrado: {local_path}"}
    return _run("upload", local_path)


@mcp.tool()
def download_url(url: str, filename: str | None = None) -> Any:
    """Baixa uma URL de mídia (resultado de uma geração) pra _shared/assets/ (persistente).

    Útil quando a geração não embutiu a URL no JSON e o download automático não pegou.
    """
    return _download(url, filename)


# ============================================================
# Escape hatch
# ============================================================

@mcp.tool()
def raw(args: list[str], parse_json: bool = True, download: bool = False) -> Any:
    """Executa `higgsfield <args>` cru (qualquer subcomando/flag fora do mapeado).

    args: lista de argumentos, ex.: ['account','credits'] ou
          ['generate','create','nano_banana_2','--prompt','...','--wait'].
    download: se True, tenta baixar mídias do resultado pra _shared/assets/.

    Retorna a saída do CLI (e, com download=True, {"result":..., "saved":[...]}).
    """
    result = _run(*[str(a) for a in args], parse_json=parse_json)
    if download and not (isinstance(result, dict) and "error" in result):
        return {"result": result, "saved": _harvest_media(result)}
    return result


if __name__ == "__main__":
    _ensure_assets()
    mcp.run()
