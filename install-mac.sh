#!/usr/bin/env bash
#
# Instalador de Maceto para macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/x1010x/maceto/main/install-mac.sh | bash
#
# Clona Maceto en ~/maceto, prepara el entorno y te deja los lanzadores
# listos. La detección de género por IA (530 MB) es aparte y opcional.

set -euo pipefail

MACETO_DIR="${MACETO_DIR:-$HOME/maceto}"
REPO="${MACETO_REPO:-https://github.com/x1010x/maceto.git}"
DRY="${MACETO_DRY_RUN:-0}"

bold=$'\033[1m'; green=$'\033[32m'; yellow=$'\033[33m'; red=$'\033[31m'; off=$'\033[0m'
step() { printf "\n%s▸ %s%s\n" "$bold" "$1" "$off"; }
ok()   { printf "  %s✓%s %s\n" "$green" "$off" "$1"; }
warn() { printf "  %s!%s %s\n" "$yellow" "$off" "$1"; }
die()  { printf "\n%s✗ %s%s\n" "$red" "$1" "$off" >&2; exit 1; }
run()  { if [ "$DRY" = "1" ]; then printf "  [dry-run] %s\n" "$*"; else "$@"; fi; }

ask_yes_no() {
    [ -n "${MACETO_YES:-}" ] && return 0
    [ -r /dev/tty ] || return 0
    printf "  %s [S/n] " "$1" > /dev/tty
    read -r r < /dev/tty || r=""
    case "$r" in [nN]*) return 1 ;; *) return 0 ;; esac
}

[ "$(uname -s)" = "Darwin" ] || die "Esto es el instalador de macOS."
printf "%s\n" "${bold}Maceto — instalador para macOS${off}"

# ---------- git ----------
step "Comprobando git"
if ! command -v git >/dev/null 2>&1; then
    run xcode-select --install || true
    die "Acepta la ventana de las Command Line Tools y vuelve a lanzar esto."
fi
ok "git $(git --version | awk '{print $3}')"

# ---------- Python 3.10+ ----------
step "Comprobando Python 3.10+"
PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3.10 \
         /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    r="$(command -v "$c" 2>/dev/null)" || continue
    if "$r" -c 'import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
        PY="$r"; break
    fi
done
if [ -z "$PY" ]; then
    warn "No encuentro Python 3.10 o superior."
    if command -v brew >/dev/null 2>&1 && ask_yes_no "¿Lo instalo con Homebrew?"; then
        run brew install python
        PY="$(command -v python3)"
    else
        die "Instala Python 3.10+ (brew install python, o python.org) y repite."
    fi
fi
ok "$("$PY" -V 2>&1)"

# ---------- el código ----------
step "Maceto en $MACETO_DIR"
ver_de() { grep -m1 "MACETO -" "$1/maceto.py" >/dev/null 2>&1 && echo ok; }
if [ -d "$MACETO_DIR/.git" ]; then
    run git -C "$MACETO_DIR" pull --ff-only
    ok "Actualizado"
elif [ -e "$MACETO_DIR" ]; then
    die "$MACETO_DIR existe y no es un clon de git. Muévelo o usa MACETO_DIR=/otra/ruta"
else
    run git clone "$REPO" "$MACETO_DIR"
    ok "Clonado"
fi

# ---------- entorno ----------
step "Preparando el entorno (primera vez tarda un minuto)"
if [ "$DRY" != "1" ]; then
    [ -x "$MACETO_DIR/.venv/bin/python3" ] || "$PY" -m venv "$MACETO_DIR/.venv"
    "$MACETO_DIR/.venv/bin/pip" install --quiet --upgrade pip
    "$MACETO_DIR/.venv/bin/pip" install --quiet -r "$MACETO_DIR/requirements.txt"
fi
ok "Dependencias listas (NiceGUI, mutagen, send2trash)"

# ---------- IA opcional ----------
step "Detección de género por IA (opcional, ~530 MB)"
if [ -x "$MACETO_DIR/.venv-ia/bin/python3" ]; then
    ok "Ya instalada"
elif ask_yes_no "¿Instalo el detector de género local (Essentia, ~530 MB)?"; then
    run bash "$MACETO_DIR/instalar_deteccion.command" || \
        warn "Falló; puedes reintentarlo luego con ./instalar_deteccion.command"
else
    warn "Sin el detector. Maceto funciona igual, solo sin 'Detectar género'."
    warn "Lo instalas cuando quieras: $MACETO_DIR/instalar_deteccion.command"
fi

# ---------- final ----------
printf "\n%s✓ Maceto instalado%s\n\n" "$green" "$off"
printf "  Arráncalo con:\n"
printf "      %s/maceto.command     (organizar por género → http://localhost:8099)\n" "$MACETO_DIR"
printf "      %s/macete.command     (buscar duplicados)\n\n" "$MACETO_DIR"
printf "  O doble clic en esos ficheros desde el Finder.\n"
