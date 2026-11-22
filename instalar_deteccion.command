#!/bin/sh
# Instala el detector de genero local de Maceto (Essentia, del MTG-UPF).
#
# Es opcional: Maceto funciona sin esto, solo que sin el boton "Detectar genero".
# Ocupa ~530 MB y despues no necesita internet para nada.
#
# Essentia no publica version para todas las combinaciones de Python y macOS,
# asi que este script no adivina: prueba con los interpretes que encuentre y
# deja que pip decida si hay algo instalable. Si quieres forzar uno concreto:
#
#     PYTHON=/ruta/a/python3.11 ./instalar_deteccion.command

DIR=$(cd "$(dirname "$0")" && pwd)
VENV="$DIR/.venv-ia"
MOD="$DIR/modelos"
BASE=https://essentia.upf.edu/models
LOG=$(mktemp /tmp/maceto-ia.XXXXXX)

echo ""
echo "  Detector de genero local para Maceto"
echo "  Motor: Essentia, del Music Technology Group (UPF Barcelona)"
echo "  Ocupa unos 530 MB. Solo hay que hacerlo una vez."
echo ""
echo "  Sistema: $(sw_vers -productName 2>/dev/null) $(sw_vers -productVersion 2>/dev/null) ($(uname -m))"
echo ""

fin() { printf "\n  Pulsa Intro para cerrar. "; read -r _; exit "$1"; }

# Algunas ruedas de Essentia (la de Mac Intel, sin ir mas lejos) empaquetan
# sdl12-compat, que por dentro carga SDL2 con dlopen... y se dejan SDL2 fuera.
# El sintoma es un popup "Failed loading SDL2 library" y el proceso abortado.
# Se coge de pysdl2-dll, que publica binarios universales desde macOS 10.11.
#
# OJO: aqui no se puede importar essentia para localizar nada, porque importarla
# es justamente lo que dispara el popup. La carpeta se busca por disco.
repara_sdl2() {
    for DYL in "$VENV"/lib/python*/site-packages/essentia/.dylibs; do
        [ -d "$DYL" ] || continue
        [ -f "$DYL/libSDL-1.2.0.dylib" ] || continue
        [ -f "$DYL/libSDL2-2.0.0.dylib" ] && continue
        echo "  A esta version de Essentia le falta SDL2. Poniendolo..."
        if ! "$VENV/bin/python3" -m pip install --quiet pysdl2-dll >>"$LOG" 2>&1; then
            echo "     no he podido instalar pysdl2-dll"
            return 1
        fi
        SDL=$("$VENV/bin/python3" -c 'import os, sdl2dll; print(os.path.join(os.path.dirname(sdl2dll.__file__), "dll", "SDL2.framework", "Versions", "A", "SDL2"))' 2>>"$LOG")
        if [ -f "$SDL" ]; then
            cp "$SDL" "$DYL/libSDL2-2.0.0.dylib"
            cp "$SDL" "$DYL/libSDL2.dylib"
            echo "     SDL2 colocado."
        else
            echo "     no he encontrado el SDL2 de pysdl2-dll"
            return 1
        fi
    done
    return 0
}

prueba() {
    PY="$1"
    [ -x "$PY" ] || PY=$(command -v "$1" 2>/dev/null) || return 1
    "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,7) else 1)' 2>/dev/null || return 1
    VER=$("$PY" -V 2>&1)
    echo "  Probando $PY ($VER)"

    rm -rf "$VENV"
    if ! "$PY" -m venv "$VENV" >>"$LOG" 2>&1; then
        echo "     no se pudo crear el entorno, siguiente"
        return 1
    fi
    "$VENV/bin/python3" -m pip install --quiet --upgrade pip >>"$LOG" 2>&1

    # primero se mira si hay rueda, sin descargarla: asi los interpretes que no
    # valen se descartan en un segundo en vez de despues de medio giga
    # --only-binary evita que intente compilarlo desde cero, que no acaba nunca
    if ! "$VENV/bin/python3" -m pip download --quiet --no-deps --only-binary=:all: \
            -d "$VENV/.sonda" essentia-tensorflow >>"$LOG" 2>&1; then
        echo "     Essentia no publica version para este Python, siguiente"
        return 1
    fi
    rm -rf "$VENV/.sonda"

    echo ""
    echo "     Hay version compatible. Descargando Essentia:"
    echo "     son unos 500 MB, puede tardar varios minutos. NO lo cortes."
    echo ""
    if ! "$VENV/bin/python3" -m pip install --only-binary=:all: essentia-tensorflow; then
        echo "     fallo la instalacion, siguiente"
        return 1
    fi

    repara_sdl2
    printf "     Comprobando que arranca... "
    if "$VENV/bin/python3" -c 'import essentia.standard' >>"$LOG" 2>&1; then
        echo "vale"
        return 0
    fi
    # las ruedas antiguas estan compiladas contra NumPy 1.x
    printf "ajustando NumPy... "
    "$VENV/bin/python3" -m pip install --quiet "numpy<2" >>"$LOG" 2>&1
    if "$VENV/bin/python3" -c 'import essentia.standard' >>"$LOG" 2>&1; then
        echo "vale"
        return 0
    fi
    echo "instala pero no arranca"
    return 1
}

[ -x "$VENV/bin/python3" ] && repara_sdl2
if [ -x "$VENV/bin/python3" ] && "$VENV/bin/python3" -c 'import essentia.standard' >/dev/null 2>&1; then
    echo "  El entorno ya estaba instalado."
else
    ENCONTRADO=0
    for c in "$PYTHON" python3.11 python3.10 python3.12 python3.9 python3.8 \
             /usr/bin/python3 python3; do
        # /usr/bin/python3 suele ser el 3.8 del sistema en los Intel antiguos,
        # y ahi es justamente el unico que tiene rueda
        [ -n "$c" ] || continue
        if prueba "$c"; then ENCONTRADO=1; break; fi
    done

    if [ "$ENCONTRADO" -eq 0 ]; then
        rm -rf "$VENV"
        echo ""
        echo "  No he encontrado ningun Python con el que Essentia funcione aqui."
        echo ""
        echo "  Los que hay en este equipo:"
        for c in python3 python3.8 python3.9 python3.10 python3.11 python3.12 \
                 python3.13 python3.14 /usr/bin/python3; do
            r=$(command -v "$c" 2>/dev/null) || continue
            echo "      $r  ->  $("$r" -V 2>&1)"
        done
        echo ""
        echo "  Essentia publica versiones hasta Python 3.11 para Macs Intel"
        echo "  antiguos, y hasta 3.12/3.14 para los mas nuevos. Instala uno"
        echo "  compatible y vuelve a lanzar esto:"
        echo ""
        echo "      brew install python@3.11"
        echo "      PYTHON=\$(brew --prefix)/bin/python3.11 ./instalar_deteccion.command"
        echo ""
        echo "  Si brew no te lo sirve, bajalo de python.org/downloads"
        echo ""
        echo "  Detalle del intento: $LOG"
        fin 1
    fi
fi

mkdir -p "$MOD"
for f in feature-extractors/discogs-effnet/discogs-effnet-bs64-1.pb \
         classification-heads/genre_discogs400/genre_discogs400-discogs-effnet-1.pb \
         classification-heads/genre_discogs400/genre_discogs400-discogs-effnet-1.json; do
    n=$(basename "$f")
    if [ ! -f "$MOD/$n" ]; then
        echo "  Descargando $n..."
        curl -sfL -o "$MOD/$n" "$BASE/$f" || { echo "  Fallo la descarga de $n"; fin 1; }
    fi
done

echo "  Comprobando el conjunto..."
if echo "" | "$VENV/bin/python3" "$DIR/macetoia.py" --servidor 2>/dev/null | grep -q '"listo"'; then
    rm -f "$LOG"
    echo ""
    echo "  Listo. Arranca Maceto y veras el boton «Detectar genero»."
    fin 0
fi
echo "  Los modelos estan, pero el detector no responde. Detalle: $LOG"
fin 1
