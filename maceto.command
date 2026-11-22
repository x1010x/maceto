#!/bin/sh
# Maceto - organizador de musica por genero.
# Doble clic aqui (Mac) o ./maceto.command desde el terminal.
# La primera vez prepara el entorno; despues arranca en un segundo.
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
VENV="$DIR/.venv"

busca_python() {
    for c in python3.14 python3.13 python3.12 python3.11 python3.10 \
             /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
        ruta=$(command -v "$c" 2>/dev/null) || continue
        if "$ruta" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
            echo "$ruta"
            return 0
        fi
    done
    return 1
}

if [ ! -x "$VENV/bin/python3" ]; then
    if ! PY=$(busca_python); then
        echo ""
        echo "  Maceto necesita Python 3.10 o superior y no lo encuentro."
        echo ""
        echo "  En Mac:   brew install python"
        echo "  O bajalo de https://www.python.org/downloads/"
        echo ""
        printf "  Pulsa Intro para cerrar. "
        read -r _
        exit 1
    fi
    echo "Primera vez: preparando el entorno con $PY. Tarda un minuto..."
    "$PY" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r "$DIR/requirements.txt"
    echo "Entorno listo."
fi

echo "Arrancando Maceto. Para cerrarlo, Ctrl+C en esta ventana."
exec "$VENV/bin/python3" "$DIR/maceto.py" "$@"
