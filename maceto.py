#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MACETO - organizador de musica por genero (interfaz web local, NiceGUI).

Recorre una carpeta de origen tema a tema, propone a que carpeta de destino
mandarlo segun el tag de genero, te deja escucharlo antes de decidir, elegir
cualquier otra carpeta, crear carpetas nuevas y deshacer lo ultimo.

Uso:  maceto.py [CARPETA_ORIGEN]
      (sin argumento usa la carpeta actual)

La primera vez te pedira que elijas donde tienes tus carpetas de generos.
Se abre solo en el navegador. Para cerrarlo, Ctrl+C en el terminal.
Copyright (C) 2026 Maceto contributors

Software libre bajo la Licencia Pública General GNU, versión 3 o
posterior. Se distribuye SIN NINGUNA GARANTÍA. Ver el fichero LICENSE
o <https://www.gnu.org/licenses/>.

"""

import base64
import difflib
import json
import os
import shutil
import subprocess
import sys
import unicodedata
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from maceto_tags import read_tags, AUDIO_EXTS  # noqa: E402

from nicegui import app, run, ui  # noqa: E402

# --------------------------------------------------------------- configuracion

CONFIG_PATH = os.path.expanduser("~/.maceto.json")

CONFIG_DEFECTO = {
    "carpeta_base": "",       # carpeta que contiene los arboles de generos
    "filtro_raices": "",      # vacio = todas las subcarpetas son arboles
    "raices_destino": [],     # arboles elegidos dentro de la carpeta base
    "origen": "",
    "escribir_tag": True,
}

# Buscador de generos al que enlazamos desde cada tema. El parametro ?track=
# no esta documentado y la web bloquea las peticiones automaticas, asi que no
# se ha podido verificar: si lo ignora, la pagina abre igual y la consulta
# queda en el portapapeles para pegarla.
CHOSIC = "https://www.chosic.com/music-genre-finder/?track="
SUBMITHUB = "https://www.submithub.com/whats-my-genre"

# Detector de genero local. Vive en su propio entorno porque Essentia no tiene
# ruedas para Python 3.14 en macOS; ver macetoia.py.
AQUI = os.path.dirname(os.path.abspath(__file__))
IA_PYTHON = os.path.join(AQUI, ".venv-ia", "bin", "python3")
IA_SCRIPT = os.path.join(AQUI, "macetoia.py")
IA_MINIMO = 0.05        # por debajo de esto no se enseña

MAX_NIVEL = 0            # 0 = sin limite de profundidad
SEPARADOR_TAGS = "; "    # como se guardan varios tags en un solo campo
UMBRAL_SUGERENCIA = 0.55
MAX_SUGERENCIAS = 7
MAX_ATAJOS = 8
PUERTO = int(os.environ.get("MACETO_PUERTO", "8099"))


# ------------------------------------------------------------------ utilidades

def norm(s):
    """Minusculas, sin acentos y solo alfanumerico, para comparar nombres."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = "".join(c if c.isalnum() else " " for c in s.lower())
    return " ".join(s.split())


def puntua(consulta, nombre):
    """0..1 de parecido entre el texto de consulta y el nombre de carpeta."""
    a, b = norm(consulta), norm(nombre)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if b in a or a in b:
        return 0.85
    pa, pb = set(a.split()), set(b.split())
    comunes = pa & pb
    s = 0.0
    if comunes:
        s = 0.5 + 0.3 * (len(comunes) / float(max(len(pa), len(pb))))
    return max(s, difflib.SequenceMatcher(None, a, b).ratio() * 0.75)


def lee_config():
    cfg = dict(CONFIG_DEFECTO)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            guardado = json.load(fh)
        if isinstance(guardado, dict):
            cfg.update(guardado)
    except (OSError, ValueError):
        pass
    cfg["raices_destino"] = [r for r in cfg["raices_destino"] if os.path.isdir(r)]
    return cfg


def guarda_config():
    datos = {
        "carpeta_base": E.base,
        "filtro_raices": E.filtro_raices,
        "raices_destino": E.raices,
        "origen": E.origen,
        "escribir_tag": E.escribir_tag,
    }
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)
    except OSError as e:
        print("No se ha podido guardar %s: %s" % (CONFIG_PATH, e))


def casa_filtro(nombre, filtro):
    """Tolerante a erratas a proposito: el filtro 'EXPERIENCE' tiene que casar
    tambien con 'PSYCHEDELIC EXPERENCE', que en el disco va sin la i."""
    f, nm = norm(filtro), norm(nombre)
    if not f:
        return True
    if f in nm:
        return True
    return any(difflib.SequenceMatcher(None, f, palabra).ratio() >= 0.85
               for palabra in nm.split())


def raiz_comun():
    """Carpeta de referencia para mostrar rutas relativas y atajos."""
    if E.base and os.path.isdir(E.base):
        return E.base
    if E.raices:
        try:
            return os.path.commonpath(E.raices)
        except ValueError:
            pass
    return os.path.expanduser("~")


def ficha_destino(ruta):
    """Construye la entrada de indice de una carpeta a partir de su ruta."""
    raiz = next((r for r in E.raices
                 if ruta == r or ruta.startswith(r + os.sep)), None)
    if raiz is None:
        return None
    partes = os.path.relpath(ruta, raiz).split(os.sep)
    return {"raiz": os.path.basename(raiz), "raiz_path": raiz,
            "nombre": partes[-1], "rel": " / ".join(partes), "path": ruta,
            "nivel": len(partes), "genero": partes[0],
            "temas": cuenta_recursiva(ruta)}


def indexa_destinos():
    """Todas las carpetas de destino, hasta MAX_NIVEL de profundidad."""
    dests = []

    def recorre(carpeta, nivel):
        for hijo in subcarpetas(carpeta):
            ficha = ficha_destino(hijo)
            if ficha is None:
                continue
            dests.append(ficha)
            if not MAX_NIVEL or nivel < MAX_NIVEL:
                recorre(hijo, nivel + 1)

    for raiz in E.raices:
        if os.path.isdir(raiz):
            recorre(raiz, 1)
    return dests


def registra_destino(ruta):
    """Mete en el indice una carpeta recien creada, sin reindexar todo."""
    if ruta in E.por_path:
        return E.por_path[ruta]
    ficha = ficha_destino(ruta)
    if ficha is None:
        return None
    E.destinos.append(ficha)
    E.por_path[ruta] = ficha
    return ficha


def sugiere(consulta, destinos, limite=MAX_SUGERENCIAS, umbral=UMBRAL_SUGERENCIA):
    """[(puntuacion, destino)] de mejor a peor."""
    if not norm(consulta):
        return []
    marcados = []
    for d in destinos:
        p = puntua(consulta, d["nombre"])
        if d["nivel"] > 1:
            p *= 0.9 ** (d["nivel"] - 1)   # cuanto mas hondo, menos peso
        if p >= umbral:
            marcados.append((p, d))
    # a igualdad de puntuacion gana la carpeta mas especifica (nombre mas largo)
    marcados.sort(key=lambda t: (-t[0], -len(norm(t[1]["nombre"])),
                                 t[1]["rel"].lower()))
    return marcados[:limite]


_contador = [0]


def nonce():
    """Valor distinto en cada enlace: asi el navegador trata la URL como nueva
    y no rellena el buscador de Chosic con lo que se escribio la vez anterior."""
    _contador[0] += 1
    return _contador[0]


def pon_tags_a_este():
    """Escribe en la cancion actual los tags de sus carpetas."""
    t = E.actual
    if t is None:
        return
    try:
        _antes, despues = escribe_tags(t["path"], t.get("tags_ruta") or [])
    except Exception as e:                                 # noqa: BLE001
        ui.notify("No se ha podido escribir: %s" % e, type="negative")
        return
    t["tags"] = despues
    t["genre"] = SEPARADOR_TAGS.join(despues)
    panel_ficha.refresh()
    panel_cola.refresh()
    ui.notify("Tags: %s" % SEPARADOR_TAGS.join(despues), type="positive")


_ia = {"proc": None}


def ia_instalada():
    return os.path.exists(IA_PYTHON) and os.path.exists(IA_SCRIPT)


def _ia_proceso():
    """Arranca el detector y lo deja vivo: recargar los modelos en cada
    consulta costaria un par de segundos de mas."""
    p = _ia["proc"]
    if p is not None and p.poll() is None:
        return p
    p = subprocess.Popen([IA_PYTHON, IA_SCRIPT, "--servidor"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, bufsize=1)
    saludo = p.stdout.readline()
    if not saludo:
        raise RuntimeError("el detector no ha arrancado")
    datos = json.loads(saludo)
    if datos.get("error"):
        raise RuntimeError(datos["error"])
    _ia["proc"] = p
    return p


def ia_analiza(ruta):
    """Devuelve [{'estilo','familia','prob'}] o lanza excepcion. Va en un hilo
    aparte porque tarda unos segundos."""
    p = _ia_proceso()
    p.stdin.write(ruta + "\n")
    p.stdin.flush()
    linea = p.stdout.readline()
    if not linea:
        _ia["proc"] = None
        raise RuntimeError("el detector se ha cerrado")
    datos = json.loads(linea)
    if datos.get("error"):
        raise RuntimeError(datos["error"])
    return [g for g in datos.get("generos", []) if g["prob"] >= IA_MINIMO]


def ia_cierra():
    p = _ia["proc"]
    if p is not None and p.poll() is None:
        try:
            p.stdin.write("__salir__\n")
            p.stdin.flush()
            p.wait(timeout=5)
        except Exception:                                  # noqa: BLE001
            p.kill()
    _ia["proc"] = None


async def detecta_genero():
    t = E.actual
    if t is None:
        return
    if not ia_instalada():
        ui.notify("Falta el detector local. Instalalo con "
                  "instalar_deteccion.command", type="warning")
        return
    E.analizando = True
    panel_ficha.refresh()
    try:
        t["ia"] = await run.io_bound(ia_analiza, t["path"])
        if not t["ia"]:
            ui.notify("El modelo no lo tiene claro con este tema",
                      type="warning")
    except Exception as e:                                 # noqa: BLE001
        ui.notify("No se ha podido analizar: %s" % e, type="negative")
    finally:
        E.analizando = False
        panel_ficha.refresh()


def anade_tag_suelto(texto):
    """Mete un tag en la cancion actual."""
    t = E.actual
    if t is None or not texto:
        return
    try:
        _antes, despues = escribe_tags(t["path"], [texto])
    except Exception as e:                                 # noqa: BLE001
        ui.notify("No se ha podido escribir: %s" % e, type="negative")
        return
    t["tags"] = despues
    t["genre"] = SEPARADOR_TAGS.join(despues)
    panel_ficha.refresh()
    panel_cola.refresh()
    ui.notify("Añadido: %s" % texto, type="positive")


def sanea_nombre(texto):
    """Deja un texto valido como nombre de fichero en macOS."""
    limpio = str(texto or "")
    for malo, bueno in (("/", "-"), (":", "-"), ("\\", "-")):
        limpio = limpio.replace(malo, bueno)
    limpio = "".join(c for c in limpio if ord(c) >= 32)
    return " ".join(limpio.split()).strip(" .")


def escribe_titulo_artista(path, titulo, artista):
    """Escribe TIT2 y TPE1. Si un campo llega vacio, se borra."""
    from mutagen.id3 import ID3, TIT2, TPE1, ID3NoHeaderError
    nuevo = False
    try:
        marcos = ID3(path)
    except ID3NoHeaderError:
        marcos = ID3()
        nuevo = True
    for marco, clase, valor in (("TIT2", TIT2, titulo), ("TPE1", TPE1, artista)):
        if valor:
            marcos.setall(marco, [clase(encoding=3, text=[valor])])
        else:
            marcos.delall(marco)
    marcos.save(path, v2_version=3) if nuevo else marcos.save(path)


def guarda_ficha(titulo, artista):
    """Guarda titulo y artista del tema actual en el propio MP3."""
    t = E.actual
    if t is None:
        return
    titulo = " ".join(str(titulo or "").split())
    artista = " ".join(str(artista or "").split())
    if titulo == (t.get("title") or "") and artista == (t.get("artist") or ""):
        return
    try:
        escribe_titulo_artista(t["path"], titulo, artista)
    except Exception as e:                                 # noqa: BLE001
        ui.notify("No se ha podido guardar: %s" % e, type="negative")
        return
    t["title"], t["artist"] = titulo, artista
    panel_ficha.refresh()
    panel_cola.refresh()
    ui.notify("Guardado en el MP3", type="positive")


def renombra_actual(nombre):
    """Cambia el nombre del fichero del tema actual."""
    t = E.actual
    if t is None:
        return
    base, ext = os.path.splitext(sanea_nombre(nombre))
    if not base:
        ui.notify("El nombre no puede quedar vacio", type="warning")
        return
    if not ext:
        ext = os.path.splitext(t["file"])[1]
    nuevo_nombre = base + ext
    if nuevo_nombre == t["file"]:
        return
    carpeta = os.path.dirname(t["path"])
    destino = os.path.join(carpeta, nuevo_nombre)
    if os.path.exists(destino):
        ui.notify("Ya hay un fichero con ese nombre en la carpeta",
                  type="warning")
        return
    para_reproductor()
    try:
        mueve_con_companero(t["path"], destino)
    except Exception as e:                                 # noqa: BLE001
        ui.notify("No se ha podido renombrar: %s" % e, type="negative")
        return
    t["path"], t["file"] = destino, nuevo_nombre
    carga_pista_en_reproductor()          # el <audio> apuntaba al nombre viejo
    panel_ficha.refresh()
    panel_cola.refresh()
    ui.notify("Renombrado: %s" % nuevo_nombre, type="positive")


def de_tags_a_fichero():
    """Nombre de fichero a partir de artista y titulo."""
    t = E.actual
    if t is None:
        return
    artista = " ".join((t.get("artist") or "").split())
    titulo = " ".join((t.get("title") or "").split())
    if not titulo and not artista:
        ui.notify("Este tema no tiene ni titulo ni artista en los tags",
                  type="warning")
        return
    propuesta = "%s - %s" % (artista, titulo) if artista and titulo \
        else (titulo or artista)
    renombra_actual(propuesta + os.path.splitext(t["file"])[1])


def de_fichero_a_tags():
    """Artista y titulo a partir del nombre del fichero: 'Artista - Titulo'."""
    t = E.actual
    if t is None:
        return
    base = os.path.splitext(t["file"])[0]
    # el separador habitual es " - "; si no lo hay, todo es titulo
    if " - " in base:
        artista, titulo = base.split(" - ", 1)
    else:
        artista, titulo = t.get("artist") or "", base
    guarda_ficha(titulo.strip(), artista.strip())


def quita_tag_suelto(texto):
    t = E.actual
    if t is None:
        return
    quedan = [x for x in (t.get("tags") or []) if norm(x) != norm(texto)]
    try:
        escribe_tags(t["path"], quedan, reemplazar=True)
    except Exception as e:                                 # noqa: BLE001
        ui.notify("No se ha podido quitar: %s" % e, type="negative")
        return
    t["tags"] = quedan
    t["genre"] = SEPARADOR_TAGS.join(quedan)
    panel_ficha.refresh()
    panel_cola.refresh()
    ui.notify("Quitado: %s" % texto)


def copia_consulta(texto):
    ui.clipboard.write(texto)
    ui.notify("Copiado: %s  (pegalo con Cmd+V en el buscador)" % texto)


def etiqueta_calidad(p):
    if p >= 0.999:
        return "exacta"
    if p >= 0.85:
        return "contiene"
    return "parecida"


def tags_de_ruta(fichero, base):
    """Los tags de una cancion son las carpetas que la separan de la base.

    base/PSYCHEDELIC EXPERIENCE/PSYTRANCE/Hi Tech/x.mp3
        -> ["PSYCHEDELIC EXPERIENCE", "PSYTRANCE", "Hi Tech"]

    Cada carpeta es un subgenero, a cualquier profundidad.
    """
    try:
        rel = os.path.relpath(os.path.dirname(os.path.abspath(fichero)),
                              os.path.abspath(base))
    except ValueError:
        return []
    if rel in (".", ""):
        return []
    partes = [t for t in rel.split(os.sep) if t not in ("", ".", "..")]
    return sin_repetir(partes)


def sin_repetir(tags):
    """Quita repetidos sin mirar mayusculas ni acentos, conservando el orden."""
    salida, vistos = [], set()
    for t in tags:
        t = " ".join(str(t).split())
        if not t:
            continue
        clave = norm(t)
        if clave and clave not in vistos:
            vistos.add(clave)
            salida.append(t)
    return salida


def parte_tags(texto):
    """Separa un campo de genero en tags sueltos."""
    if not texto:
        return []
    trozos = [texto]
    for sep in (";", "/", ","):
        trozos = [x for t in trozos for x in t.split(sep)]
    return sin_repetir(trozos)


def lee_tags_genero(path):
    """Los tags que ya tiene el fichero en el campo de genero."""
    from mutagen.id3 import ID3, ID3NoHeaderError
    try:
        marcos = ID3(path).getall("TCON")
    except (ID3NoHeaderError, Exception):          # noqa: BLE001
        return []
    valores = []
    for m in marcos:
        valores.extend(str(v) for v in m.text)
    return sin_repetir([x for v in valores for x in parte_tags(v)])


def escribe_tags(path, tags, reemplazar=False):
    """Escribe los tags en el campo de genero. Devuelve (antes, despues)."""
    from mutagen.id3 import ID3, TCON, ID3NoHeaderError
    nuevo_header = False
    try:
        marcos = ID3(path)
    except ID3NoHeaderError:
        marcos = ID3()
        nuevo_header = True
    previos = []
    for m in marcos.getall("TCON"):
        previos.extend(str(v) for v in m.text)
    antes = sin_repetir([x for v in previos for x in parte_tags(v)])

    despues = sin_repetir(list(tags) if reemplazar else antes + list(tags))
    if despues == antes and not nuevo_header:
        return antes, antes
    if despues:
        marcos.setall("TCON", [TCON(encoding=3,
                                    text=[SEPARADOR_TAGS.join(despues)])])
    else:
        marcos.delall("TCON")
    if nuevo_header:
        marcos.save(path, v2_version=3)
    else:
        marcos.save(path)
    return antes, despues


def escribe_genero(path, genero):
    """Escribe TCON en el MP3. Devuelve el genero que habia antes."""
    from mutagen.id3 import ID3, TCON, ID3NoHeaderError
    nuevo_header = False
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
        nuevo_header = True
    previos = tags.getall("TCON")
    anterior = str(previos[0]) if previos else ""
    tags.setall("TCON", [TCON(encoding=3, text=[genero])])
    if nuevo_header:
        tags.save(path, v2_version=3)   # cabecera nueva -> v2.3, la mas compatible
    else:
        tags.save(path)                 # si ya existia, respetamos su version
    return anterior


def borra_genero(path):
    from mutagen.id3 import ID3
    tags = ID3(path)
    tags.delall("TCON")
    tags.save(path)


def caratula(path):
    """data: URI de la portada embebida, o None."""
    try:
        from mutagen.id3 import ID3
        pics = ID3(path).getall("APIC")
    except Exception:                                    # noqa: BLE001
        return None
    if not pics:
        return None
    p = pics[0]
    return "data:%s;base64,%s" % (p.mime,
                                  base64.b64encode(p.data).decode("ascii"))


def companero_apple(path):
    """Ruta del AppleDouble '._X.mp3' que macOS deja en exFAT."""
    d, n = os.path.split(path)
    return os.path.join(d, "._" + n)


def nombre_libre(carpeta, nombre):
    """'Tema.mp3' -> 'Tema (2).mp3' si ya existe."""
    base, ext = os.path.splitext(nombre)
    i = 2
    cand = nombre
    while os.path.exists(os.path.join(carpeta, cand)):
        cand = "%s (%d)%s" % (base, i, ext)
        i += 1
    return cand


def mueve_con_companero(src, dst):
    shutil.move(src, dst)
    comp = companero_apple(src)
    if os.path.exists(comp):
        try:
            shutil.move(comp, companero_apple(dst))
        except OSError:
            pass


# ---------------------------------------------------------------------- estado

class Estado(object):
    def __init__(self):
        self.base = ""              # carpeta que contiene los arboles
        self.filtro_raices = CONFIG_DEFECTO["filtro_raices"]
        self.raices = []            # arboles de generos elegidos
        self.origen = ""
        self.pistas = []
        self.idx = 0
        self.destinos = []
        self.por_path = {}
        self.destino = None
        self.atajos = []
        self.deshacer = []
        self.movidos = 0
        self.saltados = 0
        self.filtro = ""
        self.escribir_tag = True
        self.autoplay = False
        self.ocultar_archivados = True
        self.orden_arbol = "temas"      # "temas" o "nombre"
        self.volumen = 1.0
        self.recursivo = True
        self.orden_cola = "tags"        # "tags" (con tags primero) o "carpeta"
        self.filtro_tags = "todos"      # todos / cero / uno / varios
        self.analizando = False

    @property
    def actual(self):
        if 0 <= self.idx < len(self.pistas):
            return self.pistas[self.idx]
        return None

    @property
    def pendientes(self):
        return sum(1 for t in self.pistas if t["estado"] == "pendiente")


E = Estado()


def ficheros_de_audio(carpeta, recursivo=True):
    """Todos los audios de la carpeta, entrando en subcarpetas si se pide."""
    salida = []
    if recursivo:
        for raiz, dirs, ficheros in os.walk(carpeta):
            dirs[:] = sorted((d for d in dirs if not d.startswith(".")),
                             key=str.lower)
            for f in sorted(ficheros, key=str.lower):
                if f.startswith("."):
                    continue
                if os.path.splitext(f)[1].lower() in AUDIO_EXTS:
                    salida.append(os.path.join(raiz, f))
    else:
        try:
            nombres = sorted(os.listdir(carpeta), key=str.lower)
        except OSError:
            return []
        for f in nombres:
            ruta = os.path.join(carpeta, f)
            if (not f.startswith(".")
                    and os.path.splitext(f)[1].lower() in AUDIO_EXTS
                    and os.path.isfile(ruta)):
                salida.append(ruta)
    return salida


def carga_origen(carpeta):
    E.origen = carpeta
    E.pistas = []
    try:
        rutas = ficheros_de_audio(carpeta, E.recursivo)
    except OSError as e:
        ui.notify("No se puede leer la carpeta: %s" % e, type="negative")
        return
    for ruta in rutas:
        t = read_tags(ruta)
        t["estado"] = "pendiente"
        t["subruta"] = os.path.relpath(os.path.dirname(ruta), carpeta)
        if t["subruta"] == ".":
            t["subruta"] = ""
        t["tags"] = parte_tags(t.get("genre", ""))
        t["tags_ruta"] = tags_de_ruta(ruta, carpeta)
        E.pistas.append(t)
    ordena_cola()
    E.idx = 0
    E.movidos = 0
    E.saltados = 0
    E.deshacer = []
    E.destino = None
    E.atajos = sugiere(os.path.basename(carpeta), E.destinos,
                       limite=MAX_ATAJOS, umbral=0.85)


def ordena_cola():
    """Primero las que ya tienen tags, despues las que no. Dentro de cada
    grupo, por carpeta y nombre de fichero."""
    if E.orden_cola == "carpeta":
        E.pistas.sort(key=lambda t: (t.get("subruta", "").lower(),
                                     t["file"].lower()))
    else:
        E.pistas.sort(key=lambda t: (0 if t.get("tags") else 1,
                                     t.get("subruta", "").lower(),
                                     t["file"].lower()))


def reindexa():
    E.destinos = indexa_destinos()
    E.por_path = dict((d["path"], d) for d in E.destinos)


# ------------------------------------------------------------------- interfaz

reproductor = None          # ui.audio del tema que suena ahora


def refresca_todo():
    panel_ficha.refresh()
    panel_sugerencias.refresh()
    panel_cola.refresh()
    panel_destino.refresh()


@ui.refreshable
def panel_reproductor():
    """Crea un <audio> nuevo para cada tema.

    Cambiarle el src al elemento que ya existe no es de fiar: Vue lo parchea
    en dos ciclos de render y mientras tanto el navegador se queda con el
    audio que ya tenia cargado, asi que repite el tema anterior. Rehacer el
    elemento entero es determinista.
    """
    global reproductor
    t = E.actual
    if t is None:
        reproductor = None
        ui.label("No hay ningun tema cargado.").classes("text-grey-6 text-sm")
        return
    reproductor = ui.audio(t["path"], autoplay=E.autoplay).classes("w-full")
    # el volumen vive en el elemento, asi que al rehacerlo hay que devolverselo
    reproductor.on("volumechange",
                   lambda e: setattr(E, "volumen",
                                     float(e.args.get("v", E.volumen))),
                   js_handler="(e) => emit({v: e.target.volume})")
    if abs(E.volumen - 1.0) > 0.001:
        ui.run_javascript("const a = getHtmlElement(%d); if (a) a.volume = %.3f;"
                          % (reproductor.id, E.volumen))


def para_reproductor():
    if reproductor is not None and not reproductor.is_deleted:
        reproductor.pause()


def carga_pista_en_reproductor():
    panel_reproductor.refresh()


def ve_a(i):
    E.idx = i
    E.destino = None
    carga_pista_en_reproductor()
    refresca_todo()


def siguiente_pendiente():
    orden = list(range(E.idx + 1, len(E.pistas))) + list(range(0, E.idx + 1))
    for j in orden:
        if E.pistas[j]["estado"] == "pendiente":
            ve_a(j)
            return
    E.idx = len(E.pistas)
    E.destino = None
    carga_pista_en_reproductor()
    refresca_todo()


def elige_destino(d):
    E.destino = d
    panel_destino.refresh()
    panel_arbol.refresh()


# ---- ficha del tema ---------------------------------------------------------

@ui.refreshable
def panel_ficha():
    t = E.actual
    if t is None:
        with ui.card().classes("w-full bg-green-900"):
            ui.label("No queda nada pendiente").classes("text-2xl font-bold")
            ui.label("%d movidos · %d saltados" % (E.movidos, E.saltados))
        return
    with ui.card().classes("w-full"):
        with ui.row().classes("w-full items-start no-wrap"):
            img = caratula(t["path"])
            if img:
                ui.image(img).classes("w-28 h-28 rounded shadow").props("fit=cover")
            with ui.column().classes("gap-0 flex-grow min-w-0"):
                ui.label("tema %d de %d · %s"
                         % (E.idx + 1, len(E.pistas), t["estado"])
                         ).classes("text-xs text-grey-6")
                # titulo y artista editables: se guardan al salir del campo
                # o al pulsar Intro
                c_tit = ui.input(value=t.get("title") or "",
                                 placeholder="(sin titulo)"
                                 ).props("dense borderless"
                                         ).classes("w-full text-2xl font-bold")
                c_art = ui.input(value=t.get("artist") or "",
                                 placeholder="(sin artista)"
                                 ).props("dense borderless"
                                         ).classes("w-full text-lg text-grey-4")
                for campo in (c_tit, c_art):
                    campo.on("blur", lambda: guarda_ficha(c_tit.value,
                                                          c_art.value))
                    campo.on("keydown.enter", lambda: guarda_ficha(c_tit.value,
                                                                   c_art.value))
                with ui.row().classes("gap-2 items-center mt-2 flex-wrap"):
                    for txt in ("%s BPM" % (t.get("bpm") or "?"),
                                t.get("key") or "?",
                                t.get("duration") or "?",
                                t.get("bitrate") or "?"):
                        ui.badge(txt, color="grey-8")

                tags = t.get("tags") or []
                with ui.row().classes("gap-1 items-center mt-2 flex-wrap"):
                    ui.label("TAGS").classes("text-xs font-bold text-grey-6")
                    if not tags:
                        ui.badge("todavia ninguno", color="orange")
                    for tg in tags:
                        with ui.row().classes("items-center gap-0 bg-blue-9 "
                                              "rounded pl-2"):
                            ui.label(tg).classes("text-xs")
                            ui.button(icon="close",
                                      on_click=lambda x=tg: quita_tag_suelto(x)
                                      ).props("flat dense round size=xs"
                                              ).tooltip("quitar este tag")
                    nuevo = ui.input(placeholder="+ tag"
                                     ).props("dense borderless"
                                             ).classes("w-24 text-xs")
                    nuevo.on("keydown.enter",
                             lambda: (anade_tag_suelto(nuevo.value),
                                      nuevo.set_value("")))
                faltan = [x for x in (t.get("tags_ruta") or [])
                          if norm(x) not in set(norm(y)
                                                for y in (t.get("tags") or []))]
                if faltan:
                    with ui.row().classes("gap-1 items-center mt-1 flex-wrap"):
                        ui.label("de la ruta:").classes("text-xs text-grey-6")
                        for tg in faltan:
                            ui.badge(tg, color="grey-7")
                        ui.button("añadir a este tema",
                                  on_click=lambda: pon_tags_a_este()
                                  ).props("flat dense no-caps color=positive"
                                          ).classes("text-xs")
                puestos = set(norm(x) for x in tags)
                with ui.row().classes("gap-2 items-center mt-2 flex-wrap"):
                    ui.button("Detectar genero", icon="auto_awesome",
                              on_click=detecta_genero
                              ).props("outline dense no-caps color=purple-4"
                                      ).classes("text-xs").set_enabled(
                        not E.analizando)
                    if E.analizando:
                        ui.spinner(size="sm")
                        ui.label("analizando, unos segundos..."
                                 ).classes("text-xs text-grey-5")
                    elif not ia_instalada():
                        ui.label("(detector local no instalado)"
                                 ).classes("text-xs text-grey-6")
                if t.get("ia"):
                    with ui.row().classes("gap-1 items-center mt-1 flex-wrap"):
                        for g in t["ia"]:
                            ya = norm(g["estilo"]) in puestos
                            etiqueta = "%s  %.0f%%" % (g["estilo"],
                                                       g["prob"] * 100)
                            ui.button(("✓ " if ya else "+ ") + etiqueta,
                                      on_click=(None if ya else
                                                (lambda x=g["estilo"]:
                                                 anade_tag_suelto(x)))
                                      ).props("dense no-caps flat "
                                              + ("color=green-4" if ya
                                                 else "color=purple-3")
                                      ).classes(
                                "text-xs rounded px-2 "
                                + ("bg-green-10" if ya else "bg-purple-10")
                            ).tooltip("ya lo tiene" if ya
                                      else "añadir «%s» como tag" % g["estilo"])

                consulta = " ".join(("%s %s" % (t.get("artist") or "",
                                                t.get("title") or "")).split())
                if consulta:
                    with ui.row().classes("gap-2 items-center mt-2 flex-wrap"):
                        # enlace de verdad (<a target=_blank>): asi no lo bloquea
                        # ningun navegador, a diferencia de abrir desde el servidor
                        ui.link("Buscar el genero en Chosic  ↗",
                                CHOSIC + urllib.parse.quote(consulta)
                                + "&_=" + str(nonce()),
                                new_tab=True
                                ).classes("text-xs px-2 py-1 rounded bg-grey-9 "
                                          "no-underline text-blue-3")
                        ui.link("SubmitHub  ↗", SUBMITHUB, new_tab=True
                                ).classes("text-xs px-2 py-1 rounded bg-grey-9 "
                                          "no-underline text-blue-3").tooltip(
                            "su detector pide subir el fichero o pegar un "
                            "enlace, y da 2 usos por hora")
                        ui.button(icon="content_copy",
                                  on_click=lambda c=consulta: copia_consulta(c)
                                  ).props("flat dense round size=sm").tooltip(
                            "copiar «%s»" % consulta)
                with ui.row().classes("w-full items-center gap-1 mt-2 no-wrap"):
                    ui.label("FICHERO").classes(
                        "text-xs font-bold text-grey-6 shrink-0")
                    c_fich = ui.input(value=t["file"]
                                      ).props("dense outlined"
                                              ).classes("flex-grow text-xs")
                    c_fich.on("keydown.enter",
                              lambda: renombra_actual(c_fich.value))
                    c_fich.on("blur", lambda: renombra_actual(c_fich.value))
                    ui.button(icon="south", on_click=de_tags_a_fichero
                              ).props("flat dense round size=sm").tooltip(
                        "poner al fichero el nombre «Artista - Titulo» "
                        "de los tags")
                    ui.button(icon="north", on_click=de_fichero_a_tags
                              ).props("flat dense round size=sm").tooltip(
                        "sacar artista y titulo del nombre del fichero "
                        "y escribirlos en los tags")


# ---- sugerencias ------------------------------------------------------------

@ui.refreshable
def panel_sugerencias():
    t = E.actual
    if t is None:
        return
    genero = t.get("genre") or ""
    filas, vistos = [], set()
    for p, d in sugiere(genero, E.destinos):
        filas.append((p, d, "por el tag"))
        vistos.add(d["path"])
    if len(filas) < 3:
        base = os.path.splitext(t["file"])[0]
        for p, d in sugiere(base, E.destinos, limite=4, umbral=0.8):
            if d["path"] not in vistos:
                filas.append((p, d, "por el nombre del fichero"))
                vistos.add(d["path"])

    ui.label("COINCIDENCIAS").classes("text-xs font-bold text-grey-6 mt-3")
    if not filas:
        ui.label("Sin coincidencias%s. Elige abajo a mano."
                 % ("" if genero else " (este tema no tiene tag de genero)")
                 ).classes("text-orange")
    if genero and not any(p >= 0.999 for p, _d, _f in filas):
        ui.button('+ Crear la carpeta "%s"' % genero,
                  on_click=lambda g=genero: crear_carpeta(g)
                  ).props("outline dense no-caps color=positive"
                          ).classes("text-xs mt-1")

    for p, d, fuente in filas:
        elegido = E.destino is not None and E.destino["path"] == d["path"]
        with ui.row().classes(
                "w-full items-center gap-2 px-3 py-1 rounded cursor-pointer "
                + ("bg-primary text-white" if elegido else "hover:bg-grey-9")
        ).on("click", lambda d=d: elegido_click(d)):
            ui.label(d["rel"]).classes("font-medium")
            ui.badge("%d temas" % d.get("temas", 0), color="grey-8")
            ui.badge(d["raiz"].replace(" EXPERIENCE", "").replace(" EXPERENCE", ""),
                     color="grey-8")
            ui.label("%s · %s" % (etiqueta_calidad(p), fuente)
                     ).classes("text-xs text-grey-5 ml-auto")

    if E.atajos:
        ui.label("ATAJOS SEGUN EL NOMBRE DE LA CARPETA DE ORIGEN"
                 ).classes("text-xs font-bold text-grey-6 mt-3")
        with ui.row().classes("gap-2 flex-wrap"):
            for _p, d in E.atajos:
                ui.button(d["nombre"], on_click=lambda d=d: elegido_click(d)
                          ).props("outline dense no-caps").classes("text-xs")


def elegido_click(d):
    elige_destino(d)
    panel_sugerencias.refresh()


# ---- arbol de destinos ------------------------------------------------------

def etiqueta_nodo(d):
    return "%s   (%d)" % (d["nombre"], d.get("temas", 0))


def ordena_destinos(lista):
    """Por defecto, las carpetas con mas temas primero."""
    if E.orden_arbol == "temas":
        return sorted(lista, key=lambda x: (-x.get("temas", 0),
                                            x["nombre"].lower()))
    return sorted(lista, key=lambda x: x["nombre"].lower())


@ui.refreshable
def panel_arbol():
    f = norm(E.filtro)

    por_padre = {}
    for d in E.destinos:
        por_padre.setdefault(os.path.dirname(d["path"]), []).append(d)

    def rama(ruta, forzar=False):
        """forzar=True cuando la carpeta madre ya encaja con la busqueda:
        entonces se muestran todos sus hijos sin volver a filtrar."""
        salida = []
        for d in ordena_destinos(por_padre.get(ruta, [])):
            encaja = forzar or not f or f in norm(d["nombre"])
            hijos = rama(d["path"], forzar=encaja)
            if not encaja and not hijos:
                continue
            nodo = {"id": d["path"], "label": etiqueta_nodo(d)}
            if hijos:
                nodo["children"] = hijos
            salida.append(nodo)
        return salida

    nodos = []
    for raiz in E.raices:
        if not os.path.isdir(raiz):
            continue
        hijos = rama(raiz)
        if not hijos and f:
            continue
        total = sum(x.get("temas", 0) for x in por_padre.get(raiz, []))
        nodos.append({"id": raiz,
                      "label": "%s   —   %d temas"
                               % (os.path.basename(raiz), total),
                      "children": hijos})

    if f and not nodos:
        ui.label('Ninguna carpeta contiene «%s».' % E.filtro).classes(
            "text-orange text-sm p-2")
        ui.button('+ Crear la carpeta "%s"' % E.filtro,
                  on_click=lambda t=E.filtro: crear_carpeta(t)
                  ).props("outline dense no-caps color=positive").classes("ml-2")
        return

    arbol = ui.tree(nodos, label_key="label", node_key="id",
                    on_select=lambda e: selecciona_nodo(e.value))
    arbol.classes("w-full")
    if E.destino is not None:
        arbol._props["selected"] = E.destino["path"]   # con props() las rutas
                                                       # con espacios se rompen
    if f:
        arbol.expand()


def selecciona_nodo(path):
    if not path:
        return
    d = E.por_path.get(path)
    if d:
        elige_destino(d)
        panel_sugerencias.refresh()
    else:
        E.destino = None              # han pulsado una de las tres raices
        panel_destino.refresh()


# ---- cola -------------------------------------------------------------------

def recarga():
    """Vuelve a leer la carpeta de origen y reindexa los destinos."""
    reindexa()
    carga_origen(E.origen)
    carga_pista_en_reproductor()
    refresca_todo()
    panel_arbol.refresh()
    ui.notify("%d temas en la carpeta · %d carpetas de destino"
              % (len(E.pistas), len(E.destinos)))


@ui.refreshable
def panel_cola():
    with ui.row().classes("w-full items-center gap-1"):
        ui.label("COLA").classes("text-xs font-bold text-grey-6")
        ui.space()
        ui.button(icon="refresh", on_click=lambda: recarga()
                  ).props("flat dense round size=sm").tooltip(
            "volver a leer la carpeta de origen")
    con_tags = sum(1 for t in E.pistas if t.get("tags"))
    cero = sum(1 for t in E.pistas if not t.get("tags"))
    uno = sum(1 for t in E.pistas if len(t.get("tags") or []) == 1)
    varios = sum(1 for t in E.pistas if len(t.get("tags") or []) >= 2)
    ui.label("%d temas · %d con tags · %d sin tags"
             % (len(E.pistas), con_tags, cero)
             ).classes("text-xs text-grey-6")
    ui.label("%d pendientes · %d archivados · %d saltados"
             % (E.pendientes, E.movidos, E.saltados)
             ).classes("text-xs text-grey-6")
    ui.checkbox("ocultar los ya archivados", value=E.ocultar_archivados,
                on_change=lambda e: (setattr(E, "ocultar_archivados", e.value),
                                     panel_cola.refresh())
                ).props("dense").classes("text-xs")
    ui.checkbox("entrar en subcarpetas", value=E.recursivo,
                on_change=lambda e: (setattr(E, "recursivo", e.value),
                                     recarga())).props("dense").classes("text-xs")
    ui.toggle({"tags": "con tags primero", "carpeta": "por carpeta"},
              value=E.orden_cola,
              on_change=lambda e: (setattr(E, "orden_cola", e.value),
                                   ordena_cola(), panel_cola.refresh())
              ).props("dense no-caps size=sm").classes("mt-1")

    # Filtrar la cola por cuantos tags tiene cada tema.
    ui.toggle({"todos": "todos (%d)" % len(E.pistas),
               "cero": "0 tags (%d)" % cero,
               "uno": "1 tag (%d)" % uno,
               "varios": "2+ tags (%d)" % varios},
              value=E.filtro_tags,
              on_change=lambda e: (setattr(E, "filtro_tags", e.value),
                                   panel_cola.refresh())
              ).props("dense no-caps size=sm").classes("mt-1")

    def _pasa_filtro(t):
        n = len(t.get("tags") or [])
        return (E.filtro_tags == "todos"
                or (E.filtro_tags == "cero" and n == 0)
                or (E.filtro_tags == "uno" and n == 1)
                or (E.filtro_tags == "varios" and n >= 2))

    visibles = [(i, t) for i, t in enumerate(E.pistas)
                if not (E.ocultar_archivados and t["estado"] != "pendiente")
                and _pasa_filtro(t)]
    with ui.column().classes("w-full gap-0 overflow-auto").style("max-height:64vh"):
        if not visibles:
            ui.label("Nada pendiente en esta carpeta." if E.pistas
                     else "La carpeta no tiene temas.").classes(
                "text-grey-6 text-sm p-2")
        for i, t in visibles:
            color = {"pendiente": "text-grey-3", "movido": "text-green-5",
                     "saltado": "text-orange-5"}[t["estado"]]
            marca = {"pendiente": "·", "movido": "✓", "saltado": "–"}[t["estado"]]
            seleccionado = (i == E.idx)
            fondo = "bg-primary text-white" if seleccionado else "hover:bg-grey-9"
            fila = ui.row().classes(
                    "w-full no-wrap items-center gap-2 px-2 py-1 rounded "
                    "cursor-pointer " + fondo).on("click", lambda i=i: ve_a(i))
            if seleccionado:
                fila.props('id=tema-seleccionado')
            with fila:
                ui.label(marca).classes(color if i != E.idx else "")
                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(t["file"]).classes(
                        "text-xs truncate " + (color if i != E.idx else ""))
                    if t.get("subruta"):
                        ui.label(t["subruta"]).classes(
                            "text-xs truncate opacity-60")
                if t.get("tags"):
                    ui.space()
                    ui.badge(str(len(t["tags"])), color="green-9"
                             ).props("floating=false").tooltip(
                        SEPARADOR_TAGS.join(t["tags"]))

    # Al re-renderizar la lista el scroll vuelve arriba y el tema en el
    # que estabas desaparece de la vista. Esto lo vuelve a centrar.
    ui.run_javascript(
        "setTimeout(() => {"
        "  const el = document.getElementById('tema-seleccionado');"
        "  if (el) el.scrollIntoView({block:'center', behavior:'auto'});"
        "}, 50)")


# ---- pie --------------------------------------------------------------------

@ui.refreshable
def panel_destino():
    if E.destino is None:
        ui.label("destino: (ninguno seleccionado)").classes("text-grey-6")
    else:
        d = E.destino
        ui.label("destino: %s / %s" % (d["raiz"], d["rel"])
                 ).classes("text-green-4 font-medium")
        if E.escribir_tag:
            ui.label("se sumaran los tags: %s"
                     % SEPARADOR_TAGS.join(sin_repetir([d["genero"],
                                                        d["nombre"]]))
                     ).classes("text-xs text-grey-5")


# ------------------------------------------------------------------- acciones

def ajusta_cuenta(destino, delta):
    """Suma o resta un tema a la carpeta y a todas sus madres hasta la raiz."""
    ruta = destino["path"]
    while ruta in E.por_path:
        d = E.por_path[ruta]
        d["temas"] = max(0, d.get("temas", 0) + delta)
        ruta = os.path.dirname(ruta)


def saltar():
    t = E.actual
    if t is None:
        return
    if t["estado"] == "pendiente":
        t["estado"] = "saltado"
        E.saltados += 1
    siguiente_pendiente()


async def mover():
    t = E.actual
    if t is None:
        return
    if E.destino is None:
        ui.notify("Elige antes una carpeta de destino", type="warning")
        return
    d = E.destino
    origen_path = t["path"]
    nombre = os.path.basename(origen_path)
    destino_path = os.path.join(d["path"], nombre)

    if os.path.exists(destino_path):
        decision = await dialogo_duplicado(t, destino_path)
        if decision is None:
            return
        if decision == "saltar":
            saltar()
            return
        if decision == "renombrar":
            nombre = nombre_libre(d["path"], nombre)
            destino_path = os.path.join(d["path"], nombre)
        elif decision == "sobrescribir":
            pass                       # shutil.move pisa el de destino

    para_reproductor()

    genero_anterior, escrito = None, False
    if E.escribir_tag and os.path.splitext(origen_path)[1].lower() == ".mp3":
        try:
            # se suma el tag de la carpeta a los que ya tenga, no los pisa:
            # con varios subgeneros por cancion, reemplazar seria destructivo
            nuevos = sin_repetir([d["genero"], d["nombre"]])
            genero_anterior, _ = escribe_tags(origen_path, nuevos)
            escrito = True
        except Exception as e:                            # noqa: BLE001
            ui.notify("No se han podido escribir los tags (%s). "
                      "Se mueve sin tocarlos." % e, type="warning")

    try:
        mueve_con_companero(origen_path, destino_path)
    except Exception as e:                                # noqa: BLE001
        ui.notify("No se ha podido mover: %s" % e, type="negative")
        return

    ajusta_cuenta(d, +1)
    t["estado"] = "movido"
    t["path"] = destino_path
    E.movidos += 1
    E.deshacer.append({"origen": origen_path, "destino": destino_path,
                       "idx": E.idx, "genero_anterior": genero_anterior,
                       "escrito": escrito})
    ui.notify("→ %s / %s" % (d["raiz"], d["rel"]), type="positive")
    siguiente_pendiente()


def deshacer():
    if not E.deshacer:
        ui.notify("No hay nada que deshacer", type="warning")
        return
    mov = E.deshacer.pop()
    para_reproductor()
    try:
        mueve_con_companero(mov["destino"], mov["origen"])
    except Exception as e:                                # noqa: BLE001
        ui.notify("No se ha podido deshacer: %s" % e, type="negative")
        return
    if mov["escrito"]:
        try:
            escribe_tags(mov["origen"], mov["genero_anterior"] or [],
                         reemplazar=True)
        except Exception:                                 # noqa: BLE001
            pass
    destino_previo = E.por_path.get(os.path.dirname(mov["destino"]))
    if destino_previo is not None:
        ajusta_cuenta(destino_previo, -1)
    i = mov["idx"]
    E.pistas[i] = read_tags(mov["origen"])
    E.pistas[i]["estado"] = "pendiente"
    E.movidos = max(0, E.movidos - 1)
    ui.notify("Deshecho: %s" % os.path.basename(mov["origen"]))
    ve_a(i)


def dialogo_duplicado(tags_origen, path_destino):
    """Devuelve un awaitable con 'saltar' | 'renombrar' | 'sobrescribir' | None."""
    tags_destino = read_tags(path_destino)
    with ui.dialog() as dlg, ui.card().classes("w-[900px] max-w-full"):
        ui.label("Ya existe un fichero con ese nombre").classes(
            "text-xl font-bold text-orange")
        ui.label(os.path.basename(path_destino)).classes(
            "text-sm text-grey-5 break-all")
        with ui.row().classes("w-full no-wrap gap-4 mt-2"):
            for titulo, tg, color in (
                    ("EL QUE MUEVES (origen)", tags_origen, "text-blue-4"),
                    ("EL QUE YA ESTA (destino)", tags_destino, "text-orange-4")):
                with ui.card().classes("flex-1 bg-grey-10"):
                    ui.label(titulo).classes("text-xs font-bold " + color)
                    ui.label(tg.get("title") or "(sin titulo)").classes("font-bold")
                    ui.label(tg.get("artist") or "(sin artista)").classes(
                        "text-sm text-grey-4")
                    ui.label("%s · %s · %s BPM · %s MB · genero: %s" % (
                        tg.get("duration") or "?", tg.get("bitrate") or "?",
                        tg.get("bpm") or "?", tg.get("size_mb") or "?",
                        tg.get("genre") or "(vacio)")).classes(
                        "text-xs text-grey-5")
                    ui.audio(tg["path"]).classes("w-full mt-2")
        with ui.row().classes("w-full justify-end gap-2 mt-3"):
            ui.button("Cancelar", on_click=lambda: dlg.submit(None)
                      ).props("flat")
            ui.button("Saltar este tema", on_click=lambda: dlg.submit("saltar")
                      ).props("outline")
            ui.button("Mover renombrando",
                      on_click=lambda: dlg.submit("renombrar")).props("outline")
            ui.button("Sobrescribir",
                      on_click=lambda: dlg.submit("sobrescribir")
                      ).props("color=negative")
    return dlg


def construye_tags_bloque(dlg, base, rutas, filas, detectados, extra):
    """Contenido del dialogo de etiquetar. Separado para poder probarlo."""
    ui.label("Aplicar tags a toda la carpeta").classes("text-lg font-bold")
    ui.label(base).classes("text-xs text-grey-6 break-all")
    ui.label("%d canciones en %d carpetas. Cada carpeta de la ruta es un "
             "tag; una cancion puede llevar varios."
             % (len(rutas), len(filas))).classes("text-xs text-grey-5")

    ui.label("TAGS DETECTADOS").classes("text-xs font-bold text-grey-6 mt-3")
    with ui.row().classes("gap-1 flex-wrap"):
        for t in detectados:
            ui.badge(t, color="primary")
    if not detectados:
        ui.label("Ninguno: las canciones estan sueltas en la raiz, sin "
                 "carpetas de las que sacar tags.").classes("text-orange")

    ui.label("DESGLOSE POR CARPETA").classes(
        "text-xs font-bold text-grey-6 mt-3")
    with ui.column().classes("w-full gap-0 overflow-auto").style(
            "max-height:30vh"):
        for sub, tags, cuantas in filas:
            with ui.row().classes("w-full items-center gap-2 px-2 py-1 "
                                  "no-wrap"):
                ui.label(sub if sub != "." else "(raiz)").classes(
                    "text-xs text-grey-5 truncate w-64 shrink-0")
                ui.label(SEPARADOR_TAGS.join(tags) or "—").classes(
                    "text-xs truncate")
                ui.space()
                ui.badge("%d" % cuantas, color="grey-8")

    campo = ui.input("Añadir mas tags a todas (separados por ;)"
                     ).classes("w-full mt-3")
    campo.on("update:model-value",
             lambda e: extra.update(texto=e.args or ""))
    casilla = ui.checkbox("Borrar los tags que ya tengan y dejar solo estos"
                          ).props("dense")
    casilla.on("update:model-value",
               lambda e: extra.update(reemplazar=bool(e.args)))
    ui.label("Sin marcar, los tags nuevos se suman a los que ya hubiera, "
             "sin repetir.").classes("text-xs text-grey-6")

    with ui.row().classes("w-full justify-end gap-2 mt-3"):
        ui.button("Cancelar", on_click=lambda: dlg.submit(None)
                  ).props("flat")
        ui.button("Aplicar a %d canciones" % len(rutas),
                  on_click=lambda: dlg.submit(True)
                  ).props("no-caps color=positive")


async def aplicar_tags_en_bloque(carpeta=None):
    """Escribe en cada cancion los tags de las carpetas que la contienen."""
    """Escribe en cada cancion los tags de las carpetas que la contienen."""
    base = carpeta or E.origen
    if not base or not os.path.isdir(base):
        ui.notify("No hay carpeta de origen", type="warning")
        return

    rutas = ficheros_de_audio(base, True)
    if not rutas:
        ui.notify("No hay canciones en %s" % os.path.basename(base),
                  type="warning")
        return

    # que tags saldrian, agrupados por subcarpeta
    por_carpeta = {}
    for r in rutas:
        por_carpeta.setdefault(os.path.dirname(r), []).append(r)
    filas = sorted((os.path.relpath(d, base), tags_de_ruta(v[0], base), len(v))
                   for d, v in por_carpeta.items())
    detectados = sin_repetir([t for _sub, tags, _n in filas for t in tags])
    extra = {"texto": "", "reemplazar": False}

    with ui.dialog().props("persistent") as dlg, \
            ui.card().classes("w-[900px] max-w-full"):
        construye_tags_bloque(dlg, base, rutas, filas, detectados, extra)
    if not await dlg:
        dlg.delete()
        return
    dlg.delete()

    anadidos = parte_tags(extra["texto"])
    reemplazar = extra["reemplazar"]
    tocados = fallos = 0
    for r in rutas:
        if os.path.splitext(r)[1].lower() != ".mp3":
            continue
        try:
            antes, despues = escribe_tags(
                r, tags_de_ruta(r, base) + anadidos, reemplazar=reemplazar)
            if despues != antes:
                tocados += 1
        except Exception:                                  # noqa: BLE001
            fallos += 1

    recarga()
    ui.notify("%d canciones etiquetadas%s"
              % (tocados, "" if not fallos else "  ·  %d fallaron" % fallos),
              type="positive" if not fallos else "warning")


async def crear_carpeta(nombre_sugerido="", padre_sugerido=None):
    """Crea una carpeta de genero (o una subcarpeta dentro de una).

    nombre_sugerido llega relleno cuando se pulsa "+ Crear la carpeta X" desde
    las coincidencias o desde el buscador del arbol.
    """
    if not E.raices:
        ui.notify("Configura antes tus carpetas de generos (boton Ajustes)",
                  type="warning")
        return

    if padre_sugerido is None and E.destino is not None:
        padre_sugerido = E.destino["path"]
        if E.destino["nivel"] == 2:
            padre_sugerido = os.path.dirname(padre_sugerido)

    # cualquier carpeta de los arboles vale como madre, mientras quede sitio
    # por debajo de MAX_NIVEL
    opciones = dict((r, os.path.basename(r) + "   (raiz)") for r in E.raices)
    for d in sorted(E.destinos, key=lambda x: (x["raiz"].lower(),
                                               x["rel"].lower())):
        if not MAX_NIVEL or d["nivel"] < MAX_NIVEL:
            opciones[d["path"]] = "%s / %s" % (d["raiz"], d["rel"])
    if padre_sugerido not in opciones:
        padre_sugerido = None

    with ui.dialog().props("persistent") as dlg, ui.card().classes("w-[620px]"):
        ui.label("Crear carpeta nueva").classes("text-lg font-bold")
        sel = ui.select(opciones,
                        value=padre_sugerido or list(opciones)[0],
                        label="Dentro de", with_input=True
                        ).classes("w-full").props("clearable")
        nom = ui.input("Nombre de la carpeta", value=nombre_sugerido
                       ).classes("w-full").props("autofocus")
        nom.on("keydown.enter", lambda: dlg.submit((sel.value, nom.value)))
        ui.label("Escribe en «Dentro de» para buscar entre tus %d carpetas. "
                 "En el nombre puedes usar barras para crear varias de golpe: "
                 "AFRO HOUSE / Black Coffee. Cada carpeta es un subgenero, y "
                 "no hay limite de niveles." % len(opciones)
                 ).classes("text-xs text-grey-6")
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancelar", on_click=lambda: dlg.submit(None)).props("flat")
            ui.button("Crear", on_click=lambda: dlg.submit((sel.value, nom.value))
                      ).props("no-caps color=positive")

    res = await dlg
    dlg.delete()
    if not res or not res[1] or not res[1].strip():
        return
    padre = res[0]
    if not padre:
        ui.notify("Elige dentro de que carpeta la creas", type="warning")
        return
    segmentos = [t.strip() for t in res[1].split("/") if t.strip()]
    if not segmentos:
        return

    nueva = padre
    ya_estaba = True
    try:
        for seg in segmentos:
            nueva = os.path.join(nueva, seg)
            if not os.path.isdir(nueva):
                ya_estaba = False
            os.makedirs(nueva, exist_ok=True)
            registra_destino(nueva)
    except OSError as e:
        ui.notify("No se ha podido crear: %s" % e, type="negative")
        return

    # registra_destino ya las metio en el indice segun se creaban: reindexar
    # entero cuesta segundos porque recuenta los temas de toda la biblioteca
    d = E.por_path.get(nueva)
    if d is None:
        ui.notify("Creada, pero fuera de tus arboles de generos", type="warning")
        return
    elige_destino(d)
    panel_arbol.refresh()
    panel_sugerencias.refresh()
    ui.notify(("Ya existia, seleccionada: %s" if ya_estaba else "Creada: %s")
              % os.path.relpath(nueva, raiz_comun()), type="positive")


def cuenta_recursiva(carpeta):
    """Temas que hay en la carpeta contando sus subcarpetas."""
    total = 0
    for _raiz, dirs, ficheros in os.walk(carpeta):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in ficheros:
            if (not f.startswith(".")
                    and os.path.splitext(f)[1].lower() in AUDIO_EXTS):
                total += 1
    return total


def cuenta_audio(carpeta):
    """Ficheros de audio que hay directamente en la carpeta (-1 si no se lee)."""
    n = 0
    try:
        with os.scandir(carpeta) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                if (e.is_file(follow_symlinks=False)
                        and os.path.splitext(e.name)[1].lower() in AUDIO_EXTS):
                    n += 1
    except OSError:
        return -1
    return n


def subcarpetas(carpeta):
    try:
        with os.scandir(carpeta) as it:
            hijos = [e.path for e in it
                     if not e.name.startswith(".")
                     and e.is_dir(follow_symlinks=False)]
    except OSError:
        return []
    return sorted(hijos, key=lambda x: os.path.basename(x).lower())


def accesos_rapidos():
    """Atajos del navegador de carpetas, deducidos de la configuracion."""
    vistos, salida = set(), []

    def mete(etiqueta, ruta):
        if ruta and os.path.isdir(ruta) and ruta not in vistos:
            vistos.add(ruta)
            salida.append((etiqueta, ruta))

    if E.base:
        mete(os.path.basename(E.base) or E.base, E.base)
        mete("arriba", os.path.dirname(E.base))
    if E.origen:
        mete("origen actual", os.path.dirname(E.origen))
    mete("Descargas", os.path.expanduser("~/Downloads"))
    mete("Casa", os.path.expanduser("~"))
    mete("Volumenes", "/Volumes")
    return salida


def construye_navegador(dlg, nav, exigir_audio=True):
    """Contenido del dialogo de elegir carpeta. Separado para poder probarlo.

    exigir_audio=True  -> solo deja confirmar carpetas que contengan temas
    exigir_audio=False -> vale cualquier carpeta (para elegir la carpeta base)
    """
    with ui.row().classes("gap-2 items-center flex-wrap"):
        ui.label("ir a:").classes("text-xs text-grey-6")
        for etiqueta, ruta in accesos_rapidos():
            ui.button(etiqueta, on_click=lambda r=ruta: navega(r)
                      ).props("outline dense no-caps").classes("text-xs")

    @ui.refreshable
    def navegador():
        actual = nav["dir"]

        # migas de pan, cada tramo pinchable
        with ui.row().classes("items-center gap-0 flex-wrap mt-1"):
            ui.button(icon="arrow_upward",
                      on_click=lambda: navega(os.path.dirname(actual))
                      ).props("flat dense round").classes("mr-2").tooltip("subir")
            acum = ""
            for parte in actual.strip("/").split("/"):
                acum += "/" + parte
                ui.button(parte, on_click=lambda r=acum: navega(r)
                          ).props("flat dense no-caps").classes("text-xs px-1")
                ui.label("/").classes("text-grey-7 text-xs")

        hijos = subcarpetas(actual)
        aqui = cuenta_audio(actual)

        with ui.column().classes("w-full gap-0 overflow-auto mt-1").style(
                "max-height:42vh"):
            if not hijos:
                ui.label("(esta carpeta no tiene subcarpetas)").classes(
                    "text-grey-6 text-sm p-2")
            for h in hijos:
                n = cuenta_audio(h)
                with ui.row().classes(
                        "w-full no-wrap items-center gap-2 px-2 py-1 rounded "
                        "cursor-pointer hover:bg-grey-9"
                ).on("click", lambda r=h: navega(r)):
                    ui.icon("folder").classes(
                        "text-amber-6" if n > 0 else "text-grey-7")
                    ui.label(os.path.basename(h)).classes("truncate")
                    ui.space()
                    if n > 0:
                        ui.badge("%d temas" % n, color="primary")
                    elif not exigir_audio:
                        ui.badge("%d subcarpetas" % len(subcarpetas(h)),
                                 color="grey-8")
                    if n > 0 or not exigir_audio:
                        ui.button(icon="check_circle",
                                  on_click=lambda r=h: dlg.submit(r)
                                  ).props("flat dense round color=positive"
                                          ).tooltip("usar esta carpeta")

        ui.separator().classes("mt-2")
        with ui.row().classes("w-full items-center gap-2 mt-2"):
            campo = ui.input(value=actual).props(
                "dense outlined").classes("flex-grow")
            campo.on("keydown.enter",
                     lambda: navega(os.path.abspath(
                         os.path.expanduser(campo.value))))
            ui.button("Cancelar", on_click=lambda: dlg.submit(None)).props("flat")
            texto = ("Usar esta carpeta (%d temas)" % max(aqui, 0)
                     if exigir_audio else "Usar esta carpeta")
            b = ui.button(texto, on_click=lambda: dlg.submit(nav["dir"])
                          ).props("no-caps color=positive")
            if exigir_audio and aqui <= 0:
                b.props("disable")

    def navega(ruta):
        if ruta and os.path.isdir(ruta):
            nav["dir"] = ruta
            navegador.refresh()

    navegador()


async def elige_carpeta(titulo, inicio, exigir_audio=True):
    """Abre el navegador de carpetas y devuelve la ruta elegida, o None."""
    nav = {"dir": inicio if inicio and os.path.isdir(inicio)
           else os.path.expanduser("~")}
    with ui.dialog().props("persistent") as dlg, \
            ui.card().classes("w-[900px] max-w-full"):
        ui.label(titulo).classes("text-lg font-bold")
        construye_navegador(dlg, nav, exigir_audio)
    ruta = await dlg
    dlg.delete()
    if not ruta:
        return None
    ruta = os.path.abspath(os.path.expanduser(ruta))
    if not os.path.isdir(ruta):
        ui.notify("No es una carpeta: %s" % ruta, type="negative")
        return None
    return ruta


def construye_ajustes(dlg, tmp):
    """Contenido del dialogo de ajustes. Separado para poder probarlo."""
    ui.label("Carpetas de generos").classes("text-lg font-bold")
    ui.label("Elige la carpeta donde tienes tus arboles de clasificacion y "
             "marca cuales son. Las subcarpetas de primer nivel de cada "
             "arbol marcado son los generos."
             ).classes("text-xs text-grey-6")

    @ui.refreshable
    def cuerpo():
        with ui.row().classes("w-full items-center gap-2 mt-3"):
            ui.icon("folder_open").classes("text-amber-6")
            ui.label(tmp["base"]).classes("text-sm truncate flex-grow")
            ui.button("Elegir carpeta...", on_click=cambia_base
                      ).props("outline dense no-caps")

        with ui.row().classes("w-full items-center gap-2 mt-2"):
            campo = ui.input(label="Solo las que contengan",
                             value=tmp["filtro"]
                             ).props("dense outlined").classes("w-64")
            campo.on("keydown.enter", lambda: aplica(campo.value))
            ui.button("Aplicar", on_click=lambda: aplica(campo.value)
                      ).props("outline dense no-caps")
            ui.label("vacio = todas").classes("text-xs text-grey-6")

        hijos = subcarpetas(tmp["base"])
        visibles = [h for h in hijos
                    if casa_filtro(os.path.basename(h), tmp["filtro"])]
        ui.label("%d de %d subcarpetas encajan"
                 % (len(visibles), len(hijos))
                 ).classes("text-xs text-grey-6 mt-2")

        with ui.column().classes("w-full gap-0 overflow-auto").style(
                "max-height:38vh"):
            if not visibles:
                ui.label("Ninguna subcarpeta encaja con ese filtro."
                         ).classes("text-orange p-2")
            for h in visibles:
                with ui.row().classes(
                        "w-full items-center gap-2 px-2 py-1 rounded "
                        "hover:bg-grey-9"):
                    ui.checkbox(
                        value=h in tmp["marcadas"],
                        on_change=lambda e, r=h: marca(r, e.value)
                    ).props("dense")
                    ui.label(os.path.basename(h)).classes(
                        "font-medium truncate")
                    ui.space()
                    ui.badge("%d generos" % len(subcarpetas(h)),
                             color="grey-8")

        ui.separator().classes("mt-2")
        with ui.row().classes("w-full justify-end items-center gap-2 mt-2"):
            ui.label("%d arboles marcados" % len(tmp["marcadas"])
                     ).classes("text-xs text-grey-6 mr-auto")
            ui.button("Cancelar", on_click=lambda: dlg.submit(None)
                      ).props("flat")
            b = ui.button("Guardar", on_click=lambda: dlg.submit(True)
                          ).props("no-caps color=positive")
            if not tmp["marcadas"]:
                b.props("disable")

    def marca(ruta, valor):
        if valor:
            tmp["marcadas"].add(ruta)
        else:
            tmp["marcadas"].discard(ruta)

    def aplica(filtro):
        tmp["filtro"] = filtro or ""
        tmp["marcadas"] = set(
            h for h in subcarpetas(tmp["base"])
            if casa_filtro(os.path.basename(h), tmp["filtro"]))
        cuerpo.refresh()

    async def cambia_base():
        ruta = await elige_carpeta("Carpeta que contiene tus generos",
                                   tmp["base"], exigir_audio=False)
        if ruta:
            tmp["base"] = ruta
            aplica(tmp["filtro"])

    cuerpo()


async def ajustes():
    """Elegir la carpeta base y que arboles de generos hay dentro."""
    tmp = {"base": E.base or raiz_comun(),
           "filtro": E.filtro_raices,
           "marcadas": set(E.raices)}
    with ui.dialog().props("persistent") as dlg, \
            ui.card().classes("w-[900px] max-w-full"):
        construye_ajustes(dlg, tmp)
    guardar = await dlg
    dlg.delete()
    if not guardar:
        return
    E.base = tmp["base"]
    E.filtro_raices = tmp["filtro"]
    E.raices = sorted(tmp["marcadas"], key=lambda x: os.path.basename(x).lower())
    reindexa()
    E.atajos = sugiere(os.path.basename(E.origen), E.destinos,
                       limite=MAX_ATAJOS, umbral=0.85)
    E.destino = None
    guarda_config()
    panel_arbol.refresh()
    refresca_todo()
    ui.notify("%d arboles · %d carpetas de genero indexadas"
              % (len(E.raices), len(E.destinos)), type="positive")


async def cambiar_origen():
    ruta = await elige_carpeta("Elegir carpeta de origen",
                               E.origen or raiz_comun(), exigir_audio=True)
    if not ruta:
        return
    carga_origen(ruta)
    guarda_config()
    cab_origen.refresh()
    carga_pista_en_reproductor()
    refresca_todo()
    panel_arbol.refresh()


@ui.refreshable
def cab_origen():
    ui.label("Origen: " + E.origen).classes("text-sm text-grey-5 truncate")


def tecla(e):
    if not e.action.keydown:
        return
    k = str(e.key)
    if k == "Enter":
        ui.timer(0.01, mover, once=True)
    elif k in ("ArrowRight", "n"):
        saltar()
    elif k in ("c", "C"):
        ui.timer(0.01, lambda: crear_carpeta(), once=True)
    elif k == "z" and (e.modifiers.meta or e.modifiers.ctrl):
        deshacer()



MANUAL = [
    ("¿Qué es Maceto?", [
        "Maceto reparte tu música en carpetas por género. Va tema a tema:",
        "te enseña una canción, lee sus tags, te propone a qué carpeta "
        "mandarla, te deja escucharla, y con un botón (o Enter) la mueve.",
        "",
        "Nada se toca hasta que tú lo decides. Mover es mover de carpeta, "
        "nunca borrar.",
    ]),
    ("De un vistazo: las tres zonas", [
        "• IZQUIERDA — la COLA: las canciones de la carpeta de origen que "
        "te quedan por repartir.",
        "• CENTRO — la FICHA del tema actual: carátula, tags, reproductor "
        "y sugerencias de a dónde va.",
        "• ABAJO — el ÁRBOL de carpetas de destino, para elegir a mano.",
    ]),
    ("Empezar: elegir carpetas", [
        "Arriba del todo:",
        "• «Cambiar carpeta…» — elige la carpeta de ORIGEN (de dónde salen "
        "las canciones a repartir).",
        "• «Ajustes» — ahí eliges tus ÁRBOLES de género (las carpetas que "
        "contienen tus subcarpetas de estilos) y otras opciones.",
        "",
        "La primera vez te pedirá dónde tienes tus carpetas de géneros.",
    ]),
    ("La cola (izquierda) y sus filtros", [
        "Arriba de la cola ves los contadores: «68 temas · 67 con tags · "
        "1 sin tags».",
        "",
        "• «ocultar los ya archivados» — esconde los que ya moviste o "
        "saltaste, para centrarte en lo que falta.",
        "• «entrar en subcarpetas» — si el origen tiene subcarpetas, también "
        "las recorre.",
        "• «con tags primero / por carpeta» — el orden de la cola: primero "
        "las que ya traen género, o tal cual en la carpeta.",
        "• Filtro por nº de tags: «todos · 0 tags · 1 tag · 2+ tags». "
        "Útil para atacar primero las que NO tienen género (0 tags), o "
        "revisar las que tienen varios.",
        "",
        "La canción en la que estás se queda MARCADA y centrada aunque "
        "cambies de tema: no tienes que buscarla con scroll.",
    ]),
    ("La ficha del tema (centro)", [
        "• Título, artista, BPM, duración y bitrate de la canción actual.",
        "• TAGS: los géneros que ya tiene. El cuadrito verde con un número "
        "en la cola es cuántos tags tiene.",
        "   – «+ tag» añade uno a mano.",
        "   – la ✕ sobre un tag lo quita.",
        "• «Detectar género» (si instalaste la IA): analiza el audio y "
        "propone estilos con su % de confianza. Haz clic en uno para "
        "añadirlo.",
        "• Las flechas ↑ ↓ pasan los tags entre el FICHERO y las CARPETAS.",
        "• «FICHERO» muestra el nombre; puedes renombrarlo ahí.",
    ]),
    ("El reproductor", [
        "Debajo de la ficha. Play/pausa y una barra para moverte por la "
        "canción y escuchar el trozo que quieras antes de decidir.",
        "",
        "En Ajustes puedes activar «Reproducir al cambiar de tema» para que "
        "cada canción suene sola al llegar a ella.",
    ]),
    ("Decidir a dónde va: sugerencias y árbol", [
        "• COINCIDENCIAS — Maceto compara los tags del tema con tus carpetas "
        "y te sugiere las que encajan. Un clic selecciona esa carpeta como "
        "destino.",
        "• «O ELIGE CUALQUIER OTRA» — si ninguna sugerencia vale, busca en "
        "el ÁRBOL de abajo. El buscador filtra carpetas por nombre.",
        "   – «nº temas / A-Z» ordena el árbol por cuántas canciones tiene "
        "cada carpeta o alfabéticamente.",
        "• «+ Carpeta nueva» (o la tecla C) — crea una carpeta de destino "
        "donde quieras.",
    ]),
    ("Mover, saltar, deshacer (abajo)", [
        "En la barra de abajo:",
        "• «MOVER AQUÍ ↵» (o la tecla Enter) — mueve la canción a la carpeta "
        "de destino seleccionada y pasa a la siguiente.",
        "• «Saltar» (o → / N) — deja esta canción para luego y pasa a la "
        "siguiente, sin moverla.",
        "• «Deshacer» (o Cmd/Ctrl + Z) — revierte el último movimiento.",
        "",
        "• «Al mover, sumar el tag de la carpeta» — al mover, le añade a la "
        "canción el género de la carpeta de destino (así queda etiquetada).",
    ]),
    ("Atajos de teclado", [
        "• Enter — Mover a la carpeta seleccionada",
        "• → (flecha derecha) o N — Saltar al siguiente",
        "• C — Crear carpeta nueva",
        "• Cmd/Ctrl + Z — Deshacer el último movimiento",
    ]),
    ("Consejos", [
        "• Empieza filtrando «0 tags» para etiquetar primero lo que no "
        "tiene género.",
        "• Usa «Detectar género» cuando no sepas qué es una canción.",
        "• Deshacer es tu amigo: si mueves mal, Cmd+Z y a otra.",
        "• Macete (el programa hermano) busca duplicados; ábrelo aparte.",
    ]),
]


def abre_ayuda():
    with ui.dialog() as dlg, ui.card().classes("w-[760px] max-w-full"):
        with ui.row().classes("w-full items-center"):
            ui.label("Manual de Maceto").classes("text-xl font-bold")
            ui.space()
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")
        with ui.scroll_area().classes("w-full").style("height:72vh"):
            for titulo, parrafos in MANUAL:
                ui.label(titulo).classes(
                    "text-base font-bold text-primary mt-4 mb-1")
                for p in parrafos:
                    if p == "":
                        ui.element("div").classes("h-1")
                    else:
                        ui.label(p).classes("text-sm leading-relaxed")
        ui.button("Entendido", on_click=dlg.close).props("unelevated")
    dlg.open()


# --------------------------------------------------------------------- pagina

@ui.page("/")
def pagina():
    ui.keyboard(on_key=tecla, ignore=["input", "select", "textarea"])
    ui.add_head_html("<style>body{-webkit-font-smoothing:antialiased}</style>")

    with ui.header().classes("items-center gap-4 py-2"):
        ui.label("MACETO").classes("text-lg font-bold tracking-widest")
        cab_origen()
        ui.space()
        ui.button("Cambiar carpeta...", on_click=cambiar_origen
                  ).props("flat dense no-caps color=white")
        ui.button("Ajustes", icon="settings", on_click=ajustes
                  ).props("flat dense no-caps color=white")
        ui.button("Ayuda", icon="help_outline", on_click=abre_ayuda
                  ).props("flat dense no-caps color=white").tooltip(
            "Manual: cómo usar Maceto")

    with ui.row().classes("w-full no-wrap gap-4 p-4"):
        # ---- columna izquierda: la cola
        with ui.column().classes("w-80 shrink-0"):
            panel_cola()

        # ---- columna derecha
        with ui.column().classes("flex-grow min-w-0 gap-2"):
            panel_ficha()

            panel_reproductor()

            panel_sugerencias()

            with ui.row().classes("w-full items-center gap-3 mt-3"):
                ui.label("O ELIGE CUALQUIER OTRA").classes(
                    "text-xs font-bold text-grey-6")
                ui.button("+ Carpeta nueva", on_click=lambda: crear_carpeta()
                          ).props("outline dense no-caps color=positive"
                                  ).classes("text-xs").tooltip(
                    "crear una carpeta donde quieras  (tecla C)")
                ui.toggle({"temas": "nº temas", "nombre": "A-Z"},
                          value=E.orden_arbol,
                          on_change=lambda e: (setattr(E, "orden_arbol", e.value),
                                               panel_arbol.refresh())
                          ).props("dense no-caps size=sm")
                ui.space()
                ui.input(placeholder="buscar carpeta...",
                         on_change=lambda e: (setattr(E, "filtro", e.value),
                                              panel_arbol.refresh())
                         ).props("dense outlined clearable").classes("w-64")
            with ui.card().classes("w-full p-2 overflow-auto").style(
                    "max-height:34vh"):
                panel_arbol()

    with ui.footer().classes("items-center gap-3 py-2 px-4"):
        ui.checkbox("Al mover, sumar el tag de la carpeta",
                    value=E.escribir_tag,
                    on_change=lambda e: (setattr(E, "escribir_tag", e.value),
                                         guarda_config(),
                                         panel_destino.refresh())
                    ).props("dense")
        ui.checkbox("Reproducir al cambiar de tema", value=E.autoplay,
                    on_change=lambda e: setattr(E, "autoplay", e.value)
                    ).props("dense")
        panel_destino()
        ui.space()
        ui.button("Etiquetar carpeta...",
                  on_click=lambda: aplicar_tags_en_bloque()
                  ).props("outline dense no-caps color=info").tooltip(
            "poner a todas las canciones los tags de sus carpetas")
        ui.button("Carpeta nueva...", on_click=lambda: crear_carpeta()
                  ).props("outline dense no-caps")
        ui.button("Deshacer", on_click=deshacer).props("outline dense no-caps")
        ui.button("Saltar", on_click=saltar).props("outline dense no-caps")
        ui.button("MOVER AQUI  ↵", on_click=mover).props(
            "dense no-caps color=positive")

    if not E.raices:
        ui.timer(0.4, ajustes, once=True)


# ------------------------------------------------------------------- arranque

def arranca():
    app.on_shutdown(ia_cierra)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    abrir = "--no-show" not in sys.argv

    cfg = lee_config()
    E.base = cfg["carpeta_base"]
    E.filtro_raices = cfg["filtro_raices"]
    E.raices = cfg["raices_destino"]
    E.escribir_tag = bool(cfg["escribir_tag"])

    if args:
        origen = os.path.abspath(os.path.expanduser(args[0]))
    elif cfg["origen"] and os.path.isdir(cfg["origen"]):
        origen = cfg["origen"]
    else:
        origen = os.getcwd()
    if not os.path.isdir(origen):
        print("No es una carpeta: %s" % origen)
        raise SystemExit(1)

    reindexa()
    carga_origen(origen)
    if E.raices:
        print("%d temas en el origen · %d carpetas de destino en %d arboles"
              % (len(E.pistas), len(E.destinos), len(E.raices)))
    else:
        print("Sin configurar: al abrir la pagina te pedira la carpeta de "
              "generos (se guarda en %s)" % CONFIG_PATH)
    ui.run(title="Maceto", port=PUERTO, dark=True,
           reload=False, show=abrir, favicon="🪴")


if __name__ in {"__main__", "__mp_main__"}:
    arranca()
