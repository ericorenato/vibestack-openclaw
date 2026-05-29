#!/usr/bin/env bash
# Instalador cross-platform do vibestack-openclaw.
# Roda em Linux (VPS), macOS e Windows (via Git Bash ou WSL).
#
# Dois modos de uso:
#   1) Dentro do repo:   ./install.sh
#   2) Direto da web:    curl -fsSL https://raw.githubusercontent.com/ericorenato/vibestack-openclaw/main/install.sh | bash
#      (nesse modo ele clona o repo sozinho e se re-executa)
#
# Idempotente: pode rodar quantas vezes quiser. Prepara tudo ate o
# 'docker compose build' e PARA — o 'docker compose up' e' manual.
set -euo pipefail

# --- helpers de output -----------------------------------------------------
if [ -t 1 ]; then
  C_GREEN="$(printf '\033[32m')"; C_YELLOW="$(printf '\033[33m')"
  C_RED="$(printf '\033[31m')"; C_BOLD="$(printf '\033[1m')"; C_OFF="$(printf '\033[0m')"
else
  C_GREEN=""; C_YELLOW=""; C_RED=""; C_BOLD=""; C_OFF=""
fi
info()  { printf '%s[install]%s %s\n' "$C_GREEN" "$C_OFF" "$*"; }
warn()  { printf '%s[install]%s %s\n' "$C_YELLOW" "$C_OFF" "$*"; }
err()   { printf '%s[install]%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; }
step()  { printf '\n%s==>%s %s%s%s\n' "$C_BOLD" "$C_OFF" "$C_BOLD" "$*" "$C_OFF"; }

# --- 0. bootstrap (curl | bash) --------------------------------------------
# Se rodando solto (sem o repo por perto), clona do GitHub e se re-executa.
REPO_URL="${OPENCLAW_REPO_URL:-https://github.com/ericorenato/vibestack-openclaw.git}"
REPO_BRANCH="${OPENCLAW_REPO_BRANCH:-main}"

SELF="${BASH_SOURCE[0]:-$0}"
if [ -f "$SELF" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$SELF")" && pwd)"
else
  SCRIPT_DIR=""   # veio de um pipe (curl | bash) — nao ha arquivo no disco
fi
# Caso especial: pipe rodando de dentro de um clone existente.
if [ -z "$SCRIPT_DIR" ] && [ -f "$PWD/docker-compose.yml" ]; then
  SCRIPT_DIR="$PWD"
fi

if [ -z "$SCRIPT_DIR" ] || [ ! -f "$SCRIPT_DIR/docker-compose.yml" ]; then
  step "Bootstrap — baixando o projeto do GitHub"
  if ! command -v git >/dev/null 2>&1; then
    err "git nao encontrado — preciso dele pra clonar o projeto."
    case "$(uname -s)" in
      Darwin*) err "No macOS: rode 'xcode-select --install' (ou instale o Git) e tente de novo." ;;
      Linux*)  err "No Linux: 'apt-get install -y git' (ou o gerenciador da sua distro)." ;;
      *)       err "Instale o Git e tente de novo." ;;
    esac
    exit 1
  fi
  TARGET="${OPENCLAW_DIR:-$PWD/vibestack-openclaw}"
  if [ -d "$TARGET/.git" ] && [ -f "$TARGET/docker-compose.yml" ]; then
    info "Repo ja' existe em $TARGET — atualizando (git pull)."
    git -C "$TARGET" pull --ff-only || warn "git pull falhou — seguindo com o que ja' esta' la'."
  elif [ -e "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ]; then
    err "$TARGET ja' existe e nao esta' vazio (e nao e' o repo)."
    err "Remova a pasta ou defina outro destino: OPENCLAW_DIR=/caminho curl ... | bash"
    exit 1
  else
    info "Clonando $REPO_URL (branch $REPO_BRANCH) em $TARGET"
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$TARGET"
  fi
  cd "$TARGET"
  info "Re-executando o instalador a partir de $TARGET"
  exec bash ./install.sh
fi

cd "$SCRIPT_DIR"

# --- detecta se da' pra fazer perguntas (tty) ------------------------------
# Com 'curl | bash' o stdin esta' ocupado pelo proprio script, entao lemos de
# /dev/tty. Se nao houver terminal (CI, etc) ou NONINTERACTIVE=1, usa defaults.
if [ "${NONINTERACTIVE:-0}" = "1" ]; then
  INTERACTIVE=0
elif { true >/dev/tty; } 2>/dev/null; then
  INTERACTIVE=1
else
  INTERACTIVE=0
fi

# ask "Pergunta" "default" -> imprime a resposta no stdout (prompt vai pro tty)
ask() {
  _p="$1"; _d="${2:-}"
  if [ "$INTERACTIVE" = "1" ]; then
    if [ -n "$_d" ]; then printf '%s [%s]: ' "$_p" "$_d" >/dev/tty
    else printf '%s: ' "$_p" >/dev/tty; fi
    IFS= read -r _a </dev/tty || _a=""
    [ -z "$_a" ] && _a="$_d"
  else
    _a="$_d"
  fi
  printf '%s' "$_a"
}

# ask_yesno "Pergunta" "y|n" -> retorna 0 (sim) ou 1 (nao)
ask_yesno() {
  _p="$1"; _d="$2"
  if [ "$INTERACTIVE" != "1" ]; then [ "$_d" = "y" ] && return 0 || return 1; fi
  _hint="s/N"; [ "$_d" = "y" ] && _hint="S/n"
  printf '%s [%s]: ' "$_p" "$_hint" >/dev/tty
  IFS= read -r _a </dev/tty || _a=""
  [ -z "$_a" ] && _a="$_d"
  case "$_a" in [sSyY]*) return 0 ;; *) return 1 ;; esac
}

# --- 1. detectar SO --------------------------------------------------------
step "Detectando sistema operacional"
OS=""
case "$(uname -s)" in
  Linux*)                 OS="linux" ;;
  Darwin*)                OS="mac" ;;
  MINGW*|MSYS*|CYGWIN*)   OS="windows" ;;
  *)                      OS="unknown" ;;
esac
info "SO detectado: $OS ($(uname -s))"
if [ "$OS" = "unknown" ]; then
  warn "SO nao reconhecido — seguindo com defaults de Linux/Unix."
  OS="linux"
fi

# --- 2. Docker -------------------------------------------------------------
step "Verificando Docker"

docker_desktop_hint() {
  err "Docker nao encontrado."
  err "No $1 nao da' pra instalar o Docker Desktop por script (app GUI)."
  err "Baixe e instale: https://www.docker.com/products/docker-desktop/"
  err "Depois abra o Docker Desktop e rode este instalador de novo."
}

if ! command -v docker >/dev/null 2>&1; then
  case "$OS" in
    linux)
      warn "Docker ausente — instalando via get.docker.com (metodo oficial)."
      if [ "$(id -u)" -eq 0 ]; then
        curl -fsSL https://get.docker.com | sh
      elif command -v sudo >/dev/null 2>&1; then
        curl -fsSL https://get.docker.com | sudo sh
      else
        err "Sem root e sem sudo — nao consigo instalar o Docker. Instale manualmente e rode de novo."
        exit 1
      fi
      ;;
    mac)     docker_desktop_hint "macOS";   exit 1 ;;
    windows) docker_desktop_hint "Windows"; exit 1 ;;
  esac
else
  info "docker encontrado: $(docker --version 2>/dev/null || echo '?')"
fi

# plugin compose v2
if ! docker compose version >/dev/null 2>&1; then
  if [ "$OS" = "linux" ]; then
    warn "Plugin 'docker compose' ausente — tentando instalar docker-compose-plugin."
    if command -v apt-get >/dev/null 2>&1; then
      if [ "$(id -u)" -eq 0 ]; then
        apt-get update -y && apt-get install -y docker-compose-plugin
      elif command -v sudo >/dev/null 2>&1; then
        sudo apt-get update -y && sudo apt-get install -y docker-compose-plugin
      fi
    fi
  fi
  if ! docker compose version >/dev/null 2>&1; then
    err "'docker compose' (v2) indisponivel. Instale o plugin do Compose e rode de novo."
    exit 1
  fi
fi
info "compose: $(docker compose version 2>/dev/null | head -n1)"

# daemon rodando?
if ! docker info >/dev/null 2>&1; then
  warn "Daemon do Docker nao esta' respondendo."
  case "$OS" in
    linux)
      if command -v systemctl >/dev/null 2>&1; then
        if [ "$(id -u)" -eq 0 ]; then systemctl start docker || true
        elif command -v sudo >/dev/null 2>&1; then sudo systemctl start docker || true
        fi
      fi
      ;;
    mac|windows)
      err "Abra o Docker Desktop e espere ficar 'running', depois rode este instalador de novo."
      ;;
  esac
  if ! docker info >/dev/null 2>&1; then
    err "Docker daemon ainda parado. Inicie o Docker e rode de novo."
    exit 1
  fi
fi
info "Docker daemon OK."

# --- 3. resolver caminhos dos volumes --------------------------------------
step "Resolvendo diretorios de dados (volumes)"
HOME_BASH="$HOME"                 # caminho do shell, usado pro mkdir
HOME_ENV="$HOME"                  # caminho gravado no .env / lido pelo Compose
if [ "$OS" = "windows" ] && command -v cygpath >/dev/null 2>&1; then
  # No Docker Desktop (Windows) o Compose entende caminho misto C:/Users/...
  # O path MSYS (/c/Users/...) NAO funciona em bind mount — por isso a conversao.
  HOME_ENV="$(cygpath -m "$HOME")"
fi
OPENCLAW_DATA_DIR_VAL="${HOME_ENV}/.openclaw"
OLLAMA_DATA_DIR_VAL="${HOME_ENV}/.ollama"
HERMES_DATA_DIR_VAL="${HOME_ENV}/.hermes"
info "OpenClaw data -> $OPENCLAW_DATA_DIR_VAL"
info "Ollama data   -> $OLLAMA_DATA_DIR_VAL"
info "Hermes data   -> $HERMES_DATA_DIR_VAL"

# --- helper de edicao in-place portavel (GNU vs BSD sed divergem) ----------
# set_env_var FILE KEY VALUE  -> grava KEY=VALUE (cria a linha se faltar)
set_env_var() {
  _file="$1"; _key="$2"; _val="$3"
  _tmp="${_file}.tmp.$$"
  if grep -q "^${_key}=" "$_file" 2>/dev/null; then
    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in
        "${_key}="*) printf '%s=%s\n' "$_key" "$_val" ;;
        *)           printf '%s\n' "$line" ;;
      esac
    done < "$_file" > "$_tmp"
    mv "$_tmp" "$_file"
  else
    printf '%s=%s\n' "$_key" "$_val" >> "$_file"
  fi
}

# get_env_var FILE KEY -> imprime o valor atual (vazio se ausente)
get_env_var() {
  grep "^$2=" "$1" 2>/dev/null | head -n1 | cut -d= -f2- || true
}

# gerador de segredo hex de 32 bytes
gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

# --- 4. preparar .env ------------------------------------------------------
step "Preparando .env"
FRESH_ENV=0
if [ ! -f .env ]; then
  cp .env.example .env
  FRESH_ENV=1
  info ".env criado a partir de .env.example"
else
  info ".env ja' existe — preservando valores."
fi

# data dirs: sobrescreve apenas se vazio ou se ainda for o default da VPS.
for pair in "OPENCLAW_DATA_DIR=$OPENCLAW_DATA_DIR_VAL" "OLLAMA_DATA_DIR=$OLLAMA_DATA_DIR_VAL" "HERMES_DATA_DIR=$HERMES_DATA_DIR_VAL"; do
  key="${pair%%=*}"; target="${pair#*=}"
  cur="$(get_env_var .env "$key")"
  case "$cur" in
    ""|"/root/.openclaw"|"/root/.ollama"|"/root/.hermes")
      set_env_var .env "$key" "$target"
      info "$key definido como $target"
      ;;
    *)
      info "$key mantido (custom): $cur"
      ;;
  esac
done

# --- 4b. perguntas interativas (so' em .env novo, com terminal) ------------
if [ "$FRESH_ENV" = "1" ] && [ "$INTERACTIVE" = "1" ]; then
  step "Configurando .env (Enter aceita o valor entre colchetes)"

  port="$(ask 'Porta do gateway OpenClaw' '18789')"
  set_env_var .env OPENCLAW_GATEWAY_PORT "$port"

  claw_port="$(ask 'Porta do Claw3D Studio (UI 3D)' '3000')"
  set_env_var .env CLAW3D_PORT "$claw_port"

  if ask_yesno 'Vai usar o MCP de Meta Ads (campanhas/insights)?' 'n'; then
    info 'Gere o token em Business Settings -> System Users -> Generate Token (escopo ads_management/ads_read).'
    meta_tok="$(ask 'META_ACCESS_TOKEN' '')"
    meta_acc="$(ask 'META_AD_ACCOUNT_ID (act_123 ou 123 — pode deixar vazio)' '')"
    set_env_var .env META_ACCESS_TOKEN "$meta_tok"
    set_env_var .env META_AD_ACCOUNT_ID "$meta_acc"
  else
    info 'Meta Ads pulado — preencha META_ACCESS_TOKEN no .env depois se mudar de ideia.'
  fi

  if ask_yesno 'Vai usar o media-editor (ffmpeg + Backblaze B2)?' 'n'; then
    b2_key="$(ask 'B2_KEY_ID' '')"
    b2_app="$(ask 'B2_APP_KEY' '')"
    b2_bucket="$(ask 'B2_BUCKET' '')"
    b2_ep="$(ask 'B2_ENDPOINT_URL' 'https://s3.us-west-002.backblazeb2.com')"
    set_env_var .env B2_KEY_ID "$b2_key"
    set_env_var .env B2_APP_KEY "$b2_app"
    set_env_var .env B2_BUCKET "$b2_bucket"
    set_env_var .env B2_ENDPOINT_URL "$b2_ep"
  else
    info 'media-editor pulado — preencha os B2_* no .env depois se precisar.'
  fi
elif [ "$FRESH_ENV" = "1" ]; then
  warn 'Sem terminal interativo — .env criado com defaults. Edite-o pra preencher Meta Ads / B2.'
fi

# --- 5. segredos -----------------------------------------------------------
step "Gerando segredos (se vazios)"
for key in OPENCLAW_GATEWAY_TOKEN GOG_KEYRING_PASSWORD HERMES_API_SERVER_KEY; do
  cur="$(get_env_var .env "$key")"
  if [ -z "$cur" ]; then
    set_env_var .env "$key" "$(gen_secret)"
    info "$key gerado."
  else
    info "$key ja' preenchido — preservado."
  fi
done

# Le os valores finais (gerados ou preservados) pra exibir no resumo abaixo.
ENV_PATH_ABS="$(pwd)/.env"
OPENCLAW_GATEWAY_TOKEN_VAL="$(get_env_var .env OPENCLAW_GATEWAY_TOKEN)"
GOG_KEYRING_PASSWORD_VAL="$(get_env_var .env GOG_KEYRING_PASSWORD)"
HERMES_API_SERVER_KEY_VAL="$(get_env_var .env HERMES_API_SERVER_KEY)"

# --- 6. normalizar entrypoint.sh para LF -----------------------------------
step "Normalizando entrypoint.sh (LF)"
if [ -f entrypoint.sh ]; then
  if grep -q $'\r' entrypoint.sh 2>/dev/null; then
    tmp="entrypoint.sh.tmp.$$"
    tr -d '\r' < entrypoint.sh > "$tmp" && mv "$tmp" entrypoint.sh
    info "CR removido do entrypoint.sh (corrige 'entrypoint not found' no Windows)."
  else
    info "entrypoint.sh ja' esta' em LF."
  fi
fi

# --- 7. criar diretorios de dados ------------------------------------------
step "Criando diretorios de dados"
mkdir -p "${HOME_BASH}/.openclaw" "${HOME_BASH}/.ollama" "${HOME_BASH}/.hermes"
info "OK: ${HOME_BASH}/.openclaw, ${HOME_BASH}/.ollama e ${HOME_BASH}/.hermes"

# --- 8. build --------------------------------------------------------------
step "Build da imagem (docker compose build)"
warn "Primeira vez leva ~5-10min (clone + pnpm/npm build + ollama)."
docker compose build

# --- 9. proximos passos (NAO sobe a stack) ---------------------------------
step "Instalacao concluida"
cat <<EOF

${C_GREEN}Pronto.${C_OFF} A imagem foi buildada. A stack ${C_BOLD}NAO${C_OFF} foi iniciada (de proposito).

Proximos passos (manuais):

  1) Suba o container (a partir de $(pwd)):
       docker compose up -d

  2) Configure o OpenClaw (uma vez por host, interativo):
       docker compose exec openclaw-vibestack openclaw configure
       docker compose up -d --force-recreate openclaw-vibestack

  3) Acesse a UI:
       - Local (Mac/Windows):  http://127.0.0.1:18789
       - VPS (do laptop):      ssh -N -L 18789:127.0.0.1:18789 root@SEU_VPS_IP
                               depois abra http://127.0.0.1:18789

  4) (Opcional) Hermes — alternativa ao OpenClaw, ja' rodando na 8642:
       - Configure o provider/modelo (uma vez):
           docker compose exec openclaw-vibestack hermes model
       - API OpenAI-compatible:
           Local:  http://127.0.0.1:8642/v1   (Bearer = HERMES_API_SERVER_KEY)
           VPS:    ssh -N -L 8642:127.0.0.1:8642 root@SEU_VPS_IP

${C_BOLD}Credenciais geradas${C_OFF} (guarde com cuidado — todas vivem em ${C_BOLD}${ENV_PATH_ABS}${C_OFF}):

  ${C_BOLD}HERMES_API_SERVER_KEY${C_OFF} = ${HERMES_API_SERVER_KEY_VAL}
      Onde usar: API key (Bearer token) pra conectar o FRONTEND na API do Hermes.
      Ex.: no Open WebUI / LobeChat / cURL aponte pra http://127.0.0.1:8642/v1 e
      use esta chave como "API Key". Via cURL:
        curl http://127.0.0.1:8642/v1/models -H "Authorization: Bearer ${HERMES_API_SERVER_KEY_VAL}"

  ${C_BOLD}OPENCLAW_GATEWAY_TOKEN${C_OFF} = ${OPENCLAW_GATEWAY_TOKEN_VAL}
      Onde usar: autentica o gateway do OpenClaw e o login do Claw3D Studio
      (mesmo segredo). A UI do OpenClaw (http://127.0.0.1:18789) pede este token.

  ${C_BOLD}GOG_KEYRING_PASSWORD${C_OFF} = ${GOG_KEYRING_PASSWORD_VAL}
      Onde usar: uso INTERNO (keyring do gog dentro do container). Nao vai em frontend.

  Pra reexibir depois: grep -E 'HERMES_API_SERVER_KEY|OPENCLAW_GATEWAY_TOKEN' "${ENV_PATH_ABS}"

Dados persistentes:
  ${OPENCLAW_DATA_DIR_VAL}
  ${OLLAMA_DATA_DIR_VAL}
  ${HERMES_DATA_DIR_VAL}

EOF
