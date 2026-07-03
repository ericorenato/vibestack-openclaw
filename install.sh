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

# roda um comando como root: direto se ja' for root, senao via sudo.
as_root() {
  if [ "$(id -u)" -eq 0 ]; then "$@"
  elif command -v sudo >/dev/null 2>&1; then sudo "$@"
  else err "Sem root e sem sudo — rode como root ou instale o sudo. Comando: $*"; return 1; fi
}

# atualiza o indice de pacotes do apt uma unica vez (memoizado).
# No-op em distros sem apt-get. Chamado antes de qualquer 'apt-get install'
# pra garantir que os repositorios Linux estejam atualizados numa maquina nova.
APT_UPDATED=0
apt_refresh() {
  command -v apt-get >/dev/null 2>&1 || return 0
  [ "$APT_UPDATED" = "1" ] && return 0
  info "Atualizando indice de pacotes do Linux (apt-get update)..."
  as_root apt-get update -y && APT_UPDATED=1
}

# garante o git instalado; instala via gerenciador de pacotes se faltar.
# Self-contained (detecta o SO via uname) pra poder ser chamada ja' no
# bootstrap, antes da deteccao de SO do passo 1.
ensure_git() {
  command -v git >/dev/null 2>&1 && return 0
  warn "Git ausente — tentando instalar."
  case "$(uname -s)" in
    Linux*)
      if command -v apt-get >/dev/null 2>&1; then
        apt_refresh && as_root apt-get install -y git
      elif command -v dnf >/dev/null 2>&1; then as_root dnf install -y git
      elif command -v yum >/dev/null 2>&1; then as_root yum install -y git
      elif command -v pacman >/dev/null 2>&1; then as_root pacman -Sy --noconfirm git
      elif command -v zypper >/dev/null 2>&1; then as_root zypper install -y git
      elif command -v apk >/dev/null 2>&1; then as_root apk add --no-cache git
      else
        err "Nenhum gerenciador de pacotes conhecido — instale o Git manualmente e rode de novo."
        return 1
      fi
      ;;
    Darwin*)
      if command -v brew >/dev/null 2>&1; then
        brew install git
      else
        err "Git ausente. Rode 'xcode-select --install' (instala o Git da Apple) ou"
        err "instale o Homebrew e use 'brew install git'; depois rode este instalador de novo."
        return 1
      fi
      ;;
    MINGW*|MSYS*|CYGWIN*)
      err "Git ausente. Instale o Git for Windows: https://git-scm.com/download/win"
      err "(No Windows voce ja' precisa do Git Bash pra rodar este instalador.)"
      return 1
      ;;
    *)
      err "Instale o Git manualmente e rode de novo."
      return 1
      ;;
  esac
  if ! command -v git >/dev/null 2>&1; then
    err "Git ainda ausente apos a tentativa de instalacao. Instale manualmente e rode de novo."
    return 1
  fi
}

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
  ensure_git || exit 1   # instala o git se faltar (preciso dele pra clonar)
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

# --- 1b. Git ---------------------------------------------------------------
# Necessario pra clonar/atualizar o repo e pro build (Dockerfile clona o
# OpenClaw via git). Rodando local (./install.sh) o git e' verificado aqui;
# no modo 'curl | bash' ele ja' foi garantido no bootstrap acima.
step "Verificando Git"
ensure_git || exit 1
info "git encontrado: $(git --version 2>/dev/null || echo '?')"

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
      apt_refresh && as_root apt-get install -y docker-compose-plugin
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
HIGGSFIELD_DATA_DIR_VAL="${HOME_ENV}/.higgsfield"
LMSTUDIO_DATA_DIR_VAL="${HOME_ENV}/.lmstudio"
EVOLUTION_DATA_DIR_VAL="${HOME_ENV}/.evolution-go"
POSTGRES_DATA_DIR_VAL="${HOME_ENV}/.evogo-pg"
info "OpenClaw data -> $OPENCLAW_DATA_DIR_VAL"
info "Ollama data   -> $OLLAMA_DATA_DIR_VAL"
info "Hermes data   -> $HERMES_DATA_DIR_VAL"
info "Higgsfield    -> $HIGGSFIELD_DATA_DIR_VAL"
info "LM Studio data-> $LMSTUDIO_DATA_DIR_VAL"
info "Evolution data-> $EVOLUTION_DATA_DIR_VAL"
info "Postgres data -> $POSTGRES_DATA_DIR_VAL"

# --- 3b. instalacao anterior? reaproveitar ou comecar do zero --------------
# Detecta diretorios de dados ja' existentes (config, modelos do Ollama,
# sessoes, bancos). Reaproveitar mantem tudo; "do zero" APAGA esses diretorios.
EXISTING_DIRS=""
for d in .openclaw .ollama .hermes .higgsfield .lmstudio .evolution-go .evogo-pg; do
  [ -d "${HOME_BASH}/${d}" ] && EXISTING_DIRS="${EXISTING_DIRS} ${HOME_BASH}/${d}"
done
if [ -n "$EXISTING_DIRS" ]; then
  step "Instalacao anterior detectada"
  for d in $EXISTING_DIRS; do info "encontrado: $d"; done
  if [ "$INTERACTIVE" = "1" ]; then
    if ask_yesno 'Reaproveitar os dados existentes? (Nao = comecar do zero, APAGA esses diretorios)' 'y'; then
      info 'Reaproveitando os dados existentes.'
    else
      warn 'Comecar do zero APAGA: config do OpenClaw/Hermes, modelos do Ollama (re-download), bancos do Evolution/Postgres.'
      if ask_yesno 'Confirma APAGAR os diretorios acima e comecar limpo?' 'n'; then
        for d in $EXISTING_DIRS; do rm -rf "$d" && info "apagado: $d"; done
      else
        info 'Reset cancelado — mantendo os dados existentes.'
      fi
    fi
  else
    info 'Sem terminal interativo — reaproveitando os dados existentes (nada e apagado).'
  fi
fi

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

# _wa_expand_br "CSV de numeros" -> CSV com as variantes BR (com/sem o 9o digito).
# WhatsApp as vezes entrega o numero BR sem o 9; registramos as duas formas pra
# o allowlist casar. Ex.: 5584996306412 -> 5584996306412,558496306412
# IDEMPOTENTE: dá pra rodar em cima de um valor ja' expandido (ex.: ao dar Enter
# pra manter o WA_BRIDGE_ALLOWED_NUMBERS atual) sem duplicar — faz dedup no final.
_wa_expand_br() {
  _exp=""; _oldifs="$IFS"; IFS=','
  for _n in $1; do
    _n=$(printf '%s' "$_n" | tr -cd '0-9')
    [ -z "$_n" ] && continue
    _exp="${_exp:+$_exp,}$_n"
    case "$_n" in
      55*)
        _len=${#_n}; _pre=$(printf '%s' "$_n" | cut -c1-4)   # 55 + DDD
        if [ "$_len" -eq 13 ] && [ "$(printf '%s' "$_n" | cut -c5)" = "9" ]; then
          _exp="$_exp,${_pre}$(printf '%s' "$_n" | cut -c6-)"     # sem o 9
        elif [ "$_len" -eq 12 ]; then
          _exp="$_exp,${_pre}9$(printf '%s' "$_n" | cut -c5-)"    # com o 9
        fi ;;
    esac
  done
  # Remove duplicatas preservando a ordem (corrige a repeticao ao reusar o valor).
  _out=""
  for _x in $_exp; do
    case ",$_out," in
      *",$_x,"*) ;;                                   # ja' esta na lista
      *) _out="${_out:+$_out,}$_x" ;;
    esac
  done
  IFS="$_oldifs"; printf '%s' "$_out"
}

# --- 4. preparar .env ------------------------------------------------------
step "Preparando .env"
FRESH_ENV=0
RECONFIG=0
if [ ! -f .env ]; then
  cp .env.example .env
  FRESH_ENV=1
  info ".env criado a partir de .env.example"
elif [ "$INTERACTIVE" = "1" ]; then
  if ask_yesno '.env ja existe. Reaproveitar como esta? (Nao = reconfigurar os valores)' 'y'; then
    info '.env reaproveitado (valores preservados).'
  else
    RECONFIG=1
    info '.env sera reconfigurado — Enter em cada pergunta MANTEM o valor atual.'
  fi
else
  info ".env ja' existe — preservando valores."
fi

# data dirs: sobrescreve apenas se vazio ou se ainda for o default da VPS.
for pair in "OPENCLAW_DATA_DIR=$OPENCLAW_DATA_DIR_VAL" "OLLAMA_DATA_DIR=$OLLAMA_DATA_DIR_VAL" "HERMES_DATA_DIR=$HERMES_DATA_DIR_VAL" "HIGGSFIELD_DATA_DIR=$HIGGSFIELD_DATA_DIR_VAL" "LMSTUDIO_DATA_DIR=$LMSTUDIO_DATA_DIR_VAL" "EVOLUTION_DATA_DIR=$EVOLUTION_DATA_DIR_VAL" "POSTGRES_DATA_DIR=$POSTGRES_DATA_DIR_VAL"; do
  key="${pair%%=*}"; target="${pair#*=}"
  cur="$(get_env_var .env "$key")"
  case "$cur" in
    ""|"/root/.openclaw"|"/root/.ollama"|"/root/.hermes"|"/root/.higgsfield"|"/root/.lmstudio"|"/root/.evolution-go"|"/root/.evogo-pg")
      set_env_var .env "$key" "$target"
      info "$key definido como $target"
      ;;
    *)
      info "$key mantido (custom): $cur"
      ;;
  esac
done

# --- 4b. perguntas interativas (.env novo OU reconfigurando, com terminal) -
# Os defaults [entre colchetes] vem do valor ATUAL do .env, entao Enter mantem
# (vale tanto pro .env recem-criado do exemplo quanto pra reconfiguracao).
if { [ "$FRESH_ENV" = "1" ] || [ "$RECONFIG" = "1" ]; } && [ "$INTERACTIVE" = "1" ]; then
  step "Configurando .env (Enter mantem o valor entre colchetes)"

  port="$(ask 'Porta do gateway OpenClaw' "$(get_env_var .env OPENCLAW_GATEWAY_PORT)")"
  set_env_var .env OPENCLAW_GATEWAY_PORT "$port"

  # Backends de modelos locais (Ollama / LM Studio). Sao build args: instala-se
  # SO' o escolhido, e o que for instalado SOBE no boot. Idempotente: o default
  # do menu reflete o que ja' esta no .env (Enter mantem). Adicionar o outro
  # depois exige novo `docker compose build`.
  cur_ol="$(get_env_var .env INSTALL_OLLAMA)";  [ -z "$cur_ol" ] && cur_ol='true'
  cur_lm="$(get_env_var .env INSTALL_LMSTUDIO)"; [ -z "$cur_lm" ] && cur_lm='false'
  if [ "$cur_ol" = "true" ] && [ "$cur_lm" = "true" ]; then
    info 'Backends locais: Ollama + LM Studio ja marcados para instalar (nada a adicionar).'
  else
    bk_def='1'
    [ "$cur_lm" = "true" ] && bk_def='2'
    printf '  Backend(s) de modelos locais a instalar no container:\n' >/dev/tty
    printf '    1) Ollama\n' >/dev/tty
    printf '    2) LM Studio (CLI lms + server OpenAI-compat na 1234)\n' >/dev/tty
    printf '    3) Ambos\n' >/dev/tty
    bk_choice="$(ask 'Qual instalar? (1/2/3)' "$bk_def")"
    case "$bk_choice" in
      2) set_env_var .env INSTALL_OLLAMA false; set_env_var .env INSTALL_LMSTUDIO true
         info 'Marcado: LM Studio.' ;;
      3) set_env_var .env INSTALL_OLLAMA true;  set_env_var .env INSTALL_LMSTUDIO true
         info 'Marcado: Ollama + LM Studio.' ;;
      *) set_env_var .env INSTALL_OLLAMA true;  set_env_var .env INSTALL_LMSTUDIO false
         info 'Marcado: Ollama.' ;;
    esac
  fi

  meta_default='n'; [ -n "$(get_env_var .env META_ACCESS_TOKEN)" ] && meta_default='y'
  if ask_yesno 'Vai usar o MCP de Meta Ads (campanhas/insights)?' "$meta_default"; then
    info 'Gere o token em Business Settings -> System Users -> Generate Token (escopo ads_management/ads_read).'
    meta_tok="$(ask 'META_ACCESS_TOKEN' "$(get_env_var .env META_ACCESS_TOKEN)")"
    meta_acc="$(ask 'META_AD_ACCOUNT_ID (act_123 ou 123 — pode deixar vazio)' "$(get_env_var .env META_AD_ACCOUNT_ID)")"
    set_env_var .env META_ACCESS_TOKEN "$meta_tok"
    set_env_var .env META_AD_ACCOUNT_ID "$meta_acc"
  else
    info 'Meta Ads pulado — preencha META_ACCESS_TOKEN no .env depois se mudar de ideia.'
  fi

  gads_default='n'; [ -n "$(get_env_var .env GOOGLE_ADS_DEVELOPER_TOKEN)" ] && gads_default='y'
  if ask_yesno 'Vai usar o MCP de Google Ads (campanhas/insights)?' "$gads_default"; then
    info 'Developer token: Google Ads -> Tools -> API Center (conta MCC).'
    info 'OAuth client "Desktop app" no Google Cloud -> client_id + client_secret.'
    gads_dev="$(ask 'GOOGLE_ADS_DEVELOPER_TOKEN' "$(get_env_var .env GOOGLE_ADS_DEVELOPER_TOKEN)")"
    gads_cid="$(ask 'GOOGLE_ADS_CLIENT_ID' "$(get_env_var .env GOOGLE_ADS_CLIENT_ID)")"
    gads_sec="$(ask 'GOOGLE_ADS_CLIENT_SECRET' "$(get_env_var .env GOOGLE_ADS_CLIENT_SECRET)")"
    gads_ref="$(ask 'GOOGLE_ADS_REFRESH_TOKEN (vazio agora — gere depois com google-ads-auth)' "$(get_env_var .env GOOGLE_ADS_REFRESH_TOKEN)")"
    gads_login="$(ask 'GOOGLE_ADS_LOGIN_CUSTOMER_ID (MCC, sem hifens — pode deixar vazio)' "$(get_env_var .env GOOGLE_ADS_LOGIN_CUSTOMER_ID)")"
    gads_acc="$(ask 'GOOGLE_ADS_CUSTOMER_ID (conta operada, sem hifens)' "$(get_env_var .env GOOGLE_ADS_CUSTOMER_ID)")"
    set_env_var .env GOOGLE_ADS_DEVELOPER_TOKEN "$gads_dev"
    set_env_var .env GOOGLE_ADS_CLIENT_ID "$gads_cid"
    set_env_var .env GOOGLE_ADS_CLIENT_SECRET "$gads_sec"
    set_env_var .env GOOGLE_ADS_REFRESH_TOKEN "$gads_ref"
    set_env_var .env GOOGLE_ADS_LOGIN_CUSTOMER_ID "$gads_login"
    set_env_var .env GOOGLE_ADS_CUSTOMER_ID "$gads_acc"
    [ -z "$gads_ref" ] && info 'Falta o refresh token: apos subir, rode `docker compose exec -it openclaw-vibestack googleads auth` e cole o GOOGLE_ADS_REFRESH_TOKEN no .env.'
  else
    info 'Google Ads pulado — preencha os GOOGLE_ADS_* no .env depois se mudar de ideia.'
  fi

  atlas_default='n'; [ -n "$(get_env_var .env ATLASCLOUD_API_KEY)" ] && atlas_default='y'
  if ask_yesno 'Vai usar o AtlasCloud (hub de 300+ modelos img/video/LLM via MCP)?' "$atlas_default"; then
    info 'Pegue a API key em https://www.atlascloud.ai/console/api-keys'
    atlas_key="$(ask 'ATLASCLOUD_API_KEY' "$(get_env_var .env ATLASCLOUD_API_KEY)")"
    set_env_var .env ATLASCLOUD_API_KEY "$atlas_key"
  else
    info 'AtlasCloud pulado — preencha ATLASCLOUD_API_KEY no .env depois se precisar.'
  fi

  b2_default='n'; [ -n "$(get_env_var .env B2_KEY_ID)" ] && b2_default='y'
  if ask_yesno 'Vai usar o media-editor (ffmpeg + Backblaze B2)?' "$b2_default"; then
    b2_ep_cur="$(get_env_var .env B2_ENDPOINT_URL)"; [ -z "$b2_ep_cur" ] && b2_ep_cur='https://s3.us-west-002.backblazeb2.com'
    b2_key="$(ask 'B2_KEY_ID' "$(get_env_var .env B2_KEY_ID)")"
    b2_app="$(ask 'B2_APP_KEY' "$(get_env_var .env B2_APP_KEY)")"
    b2_bucket="$(ask 'B2_BUCKET' "$(get_env_var .env B2_BUCKET)")"
    b2_ep="$(ask 'B2_ENDPOINT_URL' "$b2_ep_cur")"
    set_env_var .env B2_KEY_ID "$b2_key"
    set_env_var .env B2_APP_KEY "$b2_app"
    set_env_var .env B2_BUCKET "$b2_bucket"
    set_env_var .env B2_ENDPOINT_URL "$b2_ep"
  else
    info 'media-editor pulado — preencha os B2_* no .env depois se precisar.'
  fi

  # Storage S3/MinIO do Evolution p/ MIDIA RECEBIDA no WhatsApp (imagem/audio).
  # Opcional: sem isso o bridge baixa a midia on-demand (/message/downloadmedia).
  # Com isso, o Evolution sobe no bucket e manda a mediaUrl no webhook. Pode reusar
  # as credenciais do Backblaze B2 ja' informadas acima.
  minio_default='n'; [ "$(get_env_var .env EVOLUTION_MINIO_ENABLED)" = "true" ] && minio_default='y'
  if ask_yesno 'Configurar storage S3/MinIO do Evolution p/ receber midia (imagem/audio)? (opcional)' "$minio_default"; then
    info 'Enter aceita os defaults derivados do Backblaze B2 acima.'
    b2_ep_now="$(get_env_var .env B2_ENDPOINT_URL)"
    mh_default="$(printf '%s' "$b2_ep_now" | sed -E 's#^https?://##')"
    mr_default="$(printf '%s' "$mh_default" | sed -E 's/^s3\.([^.]+)\..*/\1/')"
    [ "$mr_default" = "$mh_default" ] && mr_default=""
    cur_host="$(get_env_var .env EVOLUTION_MINIO_ENDPOINT)"; [ -z "$cur_host" ] && cur_host="$mh_default"
    m_host="$(ask 'MINIO_ENDPOINT (host SEM https://)' "$cur_host")"
    cur_bucket="$(get_env_var .env EVOLUTION_MINIO_BUCKET)"; [ -z "$cur_bucket" ] && cur_bucket="$(get_env_var .env B2_BUCKET)"
    m_bucket="$(ask 'MINIO_BUCKET' "$cur_bucket")"
    cur_ak="$(get_env_var .env EVOLUTION_MINIO_ACCESS_KEY)"; [ -z "$cur_ak" ] && cur_ak="$(get_env_var .env B2_KEY_ID)"
    m_ak="$(ask 'MINIO_ACCESS_KEY' "$cur_ak")"
    cur_sk="$(get_env_var .env EVOLUTION_MINIO_SECRET_KEY)"; [ -z "$cur_sk" ] && cur_sk="$(get_env_var .env B2_APP_KEY)"
    m_sk="$(ask 'MINIO_SECRET_KEY' "$cur_sk")"
    cur_region="$(get_env_var .env EVOLUTION_MINIO_REGION)"; [ -z "$cur_region" ] && cur_region="$mr_default"
    m_region="$(ask 'MINIO_REGION' "$cur_region")"
    set_env_var .env EVOLUTION_MINIO_ENABLED true
    set_env_var .env EVOLUTION_MINIO_ENDPOINT "$m_host"
    set_env_var .env EVOLUTION_MINIO_BUCKET "$m_bucket"
    set_env_var .env EVOLUTION_MINIO_ACCESS_KEY "$m_ak"
    set_env_var .env EVOLUTION_MINIO_SECRET_KEY "$m_sk"
    set_env_var .env EVOLUTION_MINIO_REGION "$m_region"
    set_env_var .env EVOLUTION_MINIO_USE_SSL true
    info "Storage do Evolution ligado: $m_host / bucket $m_bucket (midia recebida vai pro S3)."
  else
    set_env_var .env EVOLUTION_MINIO_ENABLED false
    info 'Storage do Evolution desligado — o bridge baixa midia on-demand (/message/downloadmedia).'
  fi

  # Agente que responde o canal de WhatsApp (Telegram-like): hermes | openclaw.
  wa_agent="$(ask 'Agente que responde o WhatsApp (hermes|openclaw)' "$(get_env_var .env WA_BRIDGE_AGENT)")"
  [ -n "$wa_agent" ] && set_env_var .env WA_BRIDGE_AGENT "$wa_agent"

  # Senha do Postgres do Evolution: Enter mantem a atual; se ficar vazia, o
  # passo de segredos gera uma automaticamente.
  pg_cur="$(get_env_var .env POSTGRES_PASSWORD)"
  pg_pass="$(ask 'Senha do Postgres do WhatsApp/Evolution (Enter = manter/gerar)' "$pg_cur")"
  if [ -n "$pg_pass" ]; then
    set_env_var .env POSTGRES_PASSWORD "$pg_pass"
    info 'POSTGRES_PASSWORD definido.'
  else
    info 'POSTGRES_PASSWORD em branco — sera gerado automaticamente no passo de segredos.'
  fi

  # Allowlist do canal de WhatsApp: numeros que podem conversar com o agente.
  wa_nums="$(ask 'Seu numero de WhatsApp p/ falar com o agente (DDI+DDD+numero; vazio = qualquer um)' "$(get_env_var .env WA_BRIDGE_ALLOWED_NUMBERS)")"
  wa_nums_exp="$(_wa_expand_br "$wa_nums")"      # registra tb a variante com/sem o 9 (Brasil)
  set_env_var .env WA_BRIDGE_ALLOWED_NUMBERS "$wa_nums_exp"
  if [ -n "$wa_nums_exp" ]; then
    info "Canal WhatsApp restrito a: $wa_nums_exp"
  else
    warn 'WA_BRIDGE_ALLOWED_NUMBERS vazio — QUALQUER numero podera conversar com o agente. Edite o .env pra restringir.'
  fi

  # Proxy do WhatsApp (RECOMENDADO p/ evitar ban — Static Residential / IP fixo).
  # Preenchido = o bridge cria/edita a instancia ja' atras do proxy. Vazio = sem proxy.
  proxy_default='n'; [ -n "$(get_env_var .env EVOLUTION_PROXY_HOST)" ] && proxy_default='y'
  if ask_yesno 'Vai usar proxy no WhatsApp (Static Residential / IP fixo)?' "$proxy_default"; then
    warn 'Use IP FIXO (Static Residential). NAO use rotativo — quebra a sessao do WhatsApp Web.'
    px_proto="$(ask 'Protocolo do proxy (http|socks5)' "$(get_env_var .env EVOLUTION_PROXY_PROTOCOL)")"; [ -z "$px_proto" ] && px_proto='http'
    px_host="$(ask 'Proxy host' "$(get_env_var .env EVOLUTION_PROXY_HOST)")"
    px_port="$(ask 'Proxy porta' "$(get_env_var .env EVOLUTION_PROXY_PORT)")"
    px_user="$(ask 'Proxy usuario' "$(get_env_var .env EVOLUTION_PROXY_USERNAME)")"
    px_pass="$(ask 'Proxy senha' "$(get_env_var .env EVOLUTION_PROXY_PASSWORD)")"
    set_env_var .env EVOLUTION_PROXY_PROTOCOL "$px_proto"
    set_env_var .env EVOLUTION_PROXY_HOST "$px_host"
    set_env_var .env EVOLUTION_PROXY_PORT "$px_port"
    set_env_var .env EVOLUTION_PROXY_USERNAME "$px_user"
    set_env_var .env EVOLUTION_PROXY_PASSWORD "$px_pass"
    info "Proxy configurado: $px_proto://$px_host:$px_port (o bridge aplica na instancia no boot)."
  else
    info 'Sem proxy no WhatsApp — preencha EVOLUTION_PROXY_* no .env depois se quiser.'
  fi
elif [ "$FRESH_ENV" = "1" ]; then
  warn 'Sem terminal interativo — .env criado com defaults. Edite-o pra preencher Meta Ads / B2 / WhatsApp.'
fi

# --- 5. segredos -----------------------------------------------------------
step "Gerando segredos (se vazios)"
for key in OPENCLAW_GATEWAY_TOKEN GOG_KEYRING_PASSWORD HERMES_API_SERVER_KEY EVOLUTION_API_KEY EVOLUTION_INSTANCE_TOKEN POSTGRES_PASSWORD; do
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
EVOLUTION_API_KEY_VAL="$(get_env_var .env EVOLUTION_API_KEY)"
EVOLUTION_INSTANCE_TOKEN_VAL="$(get_env_var .env EVOLUTION_INSTANCE_TOKEN)"
POSTGRES_PASSWORD_VAL="$(get_env_var .env POSTGRES_PASSWORD)"

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
mkdir -p "${HOME_BASH}/.openclaw" "${HOME_BASH}/.ollama" "${HOME_BASH}/.hermes" "${HOME_BASH}/.higgsfield" "${HOME_BASH}/.lmstudio" "${HOME_BASH}/.evolution-go" "${HOME_BASH}/.evogo-pg"
info "OK: .openclaw, .ollama, .hermes, .higgsfield, .lmstudio, .evolution-go, .evogo-pg (em ${HOME_BASH})"

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
     Backend(s) de modelos locais escolhido(s): Ollama=$(get_env_var .env INSTALL_OLLAMA), LM Studio=$(get_env_var .env INSTALL_LMSTUDIO).
     O que foi instalado SOBE sozinho no boot. Diagnostico e (re)start manual:
       docker compose exec openclaw-vibestack models-status
       docker compose exec openclaw-vibestack start-ollama     # ou start-lmstudio
     LM Studio — baixar/carregar um modelo e conferir:
       docker compose exec openclaw-vibestack lms get <modelo>
       docker compose exec openclaw-vibestack lms load <modelo> --yes
     (Adicionar o outro backend depois exige rodar ./install.sh de novo + novo build.)

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

  5) (Opcional) Higgsfield — geracao de imagem/video (agente Criativo).
       Autentique UMA vez (abre o navegador; o token persiste no volume e
       sobrevive a restart/rebuild — so' refaca quando 'auth status' expirar):
         docker compose exec openclaw-vibestack higgsfield auth login
         docker compose exec openclaw-vibestack higgsfield auth status

  6) (Opcional) Google Ads — MCP de campanhas/insights (SDK oficial).
       Falta so' o refresh token OAuth. Gere UMA vez (fluxo headless: abre uma
       URL, voce autoriza no navegador e cola a URL de retorno):
         docker compose exec -it openclaw-vibestack googleads auth
       Copie o GOOGLE_ADS_REFRESH_TOKEN impresso pro .env e rode:
         docker compose up -d openclaw-vibestack
       Depois, leia/gerencie pelo CLI (mesmo backend dos agentes):
         docker compose exec openclaw-vibestack googleads campaigns
         docker compose exec openclaw-vibestack googleads insights

  7) (Opcional) WhatsApp via Evolution Go (servico na 8080):
       a) Ative a licenca (uma vez) no Manager:
            Local: http://127.0.0.1:8080/manager/login   (API key = EVOLUTION_API_KEY)
            VPS:   ssh -N -L 8080:127.0.0.1:8080 root@SEU_VPS_IP
       b) Pareie o QR no Manager (a instancia '${EVOLUTION_INSTANCE:-vibestack}' e' criada
          automaticamente pelo bridge no boot, com webhook + proxy + grupos desativados).
       c) 'wa_instance_status' = connected -> os agentes enviam via 'wa_send_text'.

     Defaults desta instalacao (mude no .env ou no Manager do Evolution se quiser):
       - Mensagens SAO salvas no banco (EVOLUTION_SAVE_MESSAGES=true).
       - Grupos e status SAO ignorados (EVOLUTION_IGNORE_GROUPS/STATUS=true) — canal 1:1.
       - A sessao do WhatsApp persiste no Postgres e RECONECTA sozinha apos restart.

${C_BOLD}Credenciais geradas${C_OFF} (guarde com cuidado — todas vivem em ${C_BOLD}${ENV_PATH_ABS}${C_OFF}):

  ${C_BOLD}HERMES_API_SERVER_KEY${C_OFF} = ${HERMES_API_SERVER_KEY_VAL}
      Onde usar: API key (Bearer token) pra conectar o FRONTEND na API do Hermes.
      Ex.: no Open WebUI / LobeChat / cURL aponte pra http://127.0.0.1:8642/v1 e
      use esta chave como "API Key". Via cURL:
        curl http://127.0.0.1:8642/v1/models -H "Authorization: Bearer ${HERMES_API_SERVER_KEY_VAL}"

  ${C_BOLD}OPENCLAW_GATEWAY_TOKEN${C_OFF} = ${OPENCLAW_GATEWAY_TOKEN_VAL}
      Onde usar: autentica o gateway do OpenClaw. A UI (http://127.0.0.1:18789) pede este token.

  ${C_BOLD}EVOLUTION_API_KEY${C_OFF} = ${EVOLUTION_API_KEY_VAL}
      Onde usar: ativar a licenca no Manager do Evolution Go (/manager/login) e criar instancia.
  ${C_BOLD}EVOLUTION_INSTANCE_TOKEN${C_OFF} = ${EVOLUTION_INSTANCE_TOKEN_VAL}
      Onde usar: token da instancia de WhatsApp (envio/qr/status). Definido no 'wa_create_instance'.

  ${C_BOLD}POSTGRES_PASSWORD${C_OFF} = ${POSTGRES_PASSWORD_VAL}
      Onde usar: senha do Postgres do Evolution Go (uso interno entre os servicos do compose).

  ${C_BOLD}GOG_KEYRING_PASSWORD${C_OFF} = ${GOG_KEYRING_PASSWORD_VAL}
      Onde usar: uso INTERNO (keyring do gog dentro do container). Nao vai em frontend.

  Pra reexibir depois: grep -E 'HERMES_API_SERVER_KEY|OPENCLAW_GATEWAY_TOKEN|EVOLUTION_|POSTGRES_PASSWORD' "${ENV_PATH_ABS}"

Dados persistentes:
  ${OPENCLAW_DATA_DIR_VAL}
  ${OLLAMA_DATA_DIR_VAL}
  ${HERMES_DATA_DIR_VAL}
  ${HIGGSFIELD_DATA_DIR_VAL}
  ${LMSTUDIO_DATA_DIR_VAL}
  ${EVOLUTION_DATA_DIR_VAL}
  ${POSTGRES_DATA_DIR_VAL}

EOF
