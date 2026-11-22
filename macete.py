#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MACETE - buscador de canciones duplicadas (interfaz web local, NiceGUI).

Escanea las carpetas que le digas, agrupa las canciones repetidas, y por cada
grupo eliges cual es la MASTER: esa se mueve a tu carpeta de masters y las
demas copias se van a la papelera del sistema.

Uso:  macete.py [CARPETA ...]

Hermano de maceto.py; usa otro puerto, asi que pueden estar los dos abiertos.
Copyright (C) 2026 Maceto contributors

Software libre bajo la Licencia Pública General GNU, versión 3 o
posterior. Se distribuye SIN NINGUNA GARANTÍA. Ver el fichero LICENSE
o <https://www.gnu.org/licenses/>.

"""

import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from maceto_tags import read_tags, AUDIO_EXTS  # noqa: E402

from nicegui import run, ui  # noqa: E402

try:
    from send2trash import send2trash
except ImportError:                                        # noqa: BLE001
    send2trash = None

CONFIG_PATH = os.path.expanduser("~/.macete.json")
PUERTO = int(os.environ.get("MACETE_PUERTO", "8098"))
NOMBRE_MASTERS = "_MACETE MASTERS"
TROZO = 256 * 1024
BLOQUE = 1 << 20

COLOR_MASTER = "positive"


# ------------------------------------------------------------------ utilidades

def lee_config():
    datos = {"carpetas": [], "excluidas": [], "destino": "",
             "estrategia": "fichero"}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            guardado = json.load(fh)
        if isinstance(guardado, dict):
            datos.update(guardado)
    except (OSError, ValueError):
        pass
    datos["carpetas"] = [c for c in datos["carpetas"] if os.path.isdir(c)]
    datos["excluidas"] = [c for c in datos["excluidas"] if os.path.isdir(c)]
    return datos


def guarda_config():
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump({"carpetas": E.carpetas, "excluidas": E.excluidas,
                       "destino": E.destino,
                       "estrategia": E.estrategia}, fh,
                      ensure_ascii=False, indent=2)
    except OSError as e:
        print("No se ha podido guardar %s: %s" % (CONFIG_PATH, e))


def subcarpetas(carpeta):
    try:
        with os.scandir(carpeta) as it:
            hijos = [e.path for e in it if not e.name.startswith(".")
                     and e.is_dir(follow_symlinks=False)]
    except OSError:
        return []
    return sorted(hijos, key=lambda x: os.path.basename(x).lower())


def cuenta_audio(carpeta):
    n = 0
    try:
        with os.scandir(carpeta) as it:
            for e in it:
                if (not e.name.startswith(".")
                        and e.is_file(follow_symlinks=False)
                        and os.path.splitext(e.name)[1].lower() in AUDIO_EXTS):
                    n += 1
    except OSError:
        return -1
    return n


def ficheros_de_audio(carpetas, excluir=()):
    """Todos los audios de esas carpetas, recursivo y sin repetir."""
    vistos, salida = set(), []
    excluidas = [os.path.abspath(x) for x in excluir if x]
    for base in carpetas:
        for raiz, dirs, ficheros in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if any(os.path.abspath(raiz) == x
                   or os.path.abspath(raiz).startswith(x + os.sep)
                   for x in excluidas):
                dirs[:] = []
                continue
            for f in ficheros:
                if f.startswith("."):       # incluye los ._ de macOS
                    continue
                if os.path.splitext(f)[1].lower() not in AUDIO_EXTS:
                    continue
                ruta = os.path.join(raiz, f)
                real = os.path.realpath(ruta)
                if real in vistos:
                    continue
                vistos.add(real)
                salida.append(ruta)
    return salida


def humano(n):
    for unidad in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidad == "GB":
            return "%.0f %s" % (n, unidad) if unidad != "GB" else "%.1f GB" % n
        n /= 1024.0
    return "%d B" % n


# --------------------------------------------------------------------- hashes

def rango_audio(path):
    """(inicio, fin) de los bytes de audio, saltando las etiquetas ID3.

    Asi dos copias de la misma cancion con tags distintos salen iguales.
    """
    tam = os.path.getsize(path)
    inicio, fin = 0, tam
    try:
        with open(path, "rb") as fh:
            cab = fh.read(10)
            if len(cab) == 10 and cab[:3] == b"ID3":
                tamano = 0
                for b in cab[6:10]:          # entero synchsafe de 28 bits
                    tamano = (tamano << 7) | (b & 0x7F)
                inicio = 10 + tamano
                if cab[5] & 0x10:            # hay footer
                    inicio += 10
            if tam >= 128:
                fh.seek(-128, os.SEEK_END)
                if fh.read(3) == b"TAG":     # ID3v1 al final
                    fin = tam - 128
    except OSError:
        return 0, tam
    if inicio >= fin or inicio < 0:
        return 0, tam
    return inicio, fin


def _digest(path, inicio, fin, solo_extremos):
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as fh:
        if solo_extremos and (fin - inicio) > 2 * TROZO:
            fh.seek(inicio)
            h.update(fh.read(TROZO))
            fh.seek(fin - TROZO)
            h.update(fh.read(TROZO))
        else:
            fh.seek(inicio)
            quedan = fin - inicio
            while quedan > 0:
                bloque = fh.read(min(BLOQUE, quedan))
                if not bloque:
                    break
                quedan -= len(bloque)
                h.update(bloque)
    return h.hexdigest()


def clave_barata(path, estrategia):
    """Lo que se puede comparar sin leer el fichero entero."""
    if estrategia == "audio":
        inicio, fin = rango_audio(path)
        return fin - inicio
    return os.path.getsize(path)


def huella(path, estrategia, rapida):
    inicio, fin = rango_audio(path) if estrategia == "audio" \
        else (0, os.path.getsize(path))
    return _digest(path, inicio, fin, solo_extremos=rapida)


def agrupa_duplicados(rutas, estrategia, avisa=None):
    """Embudo de tres pasos para no leer de mas: primero el tamano, luego un
    hash de los extremos, y solo al final el fichero entero."""
    def paso(grupos, fn, etiqueta):
        salida, hechos = [], 0
        total = sum(len(g) for g in grupos)
        for grupo in grupos:
            cubos = {}
            for r in grupo:
                try:
                    cubos.setdefault(fn(r), []).append(r)
                except OSError:
                    pass
                hechos += 1
                if avisa and hechos % 200 == 0:
                    avisa(etiqueta, hechos, total)
            salida.extend(v for v in cubos.values() if len(v) > 1)
        if avisa:
            avisa(etiqueta, total, total)
        return salida

    grupos = paso([list(rutas)], lambda r: clave_barata(r, estrategia),
                  "tamaño")
    if not grupos:
        return []
    grupos = paso(grupos, lambda r: huella(r, estrategia, True), "extremos")
    if not grupos:
        return []
    return paso(grupos, lambda r: huella(r, estrategia, False), "completo")


# ------------------------------------------------------------------ candidatas

def puntua_master(ficha):
    """Cuanto mejor candidata a master, mas alta la puntuacion."""
    return (len(ficha["tags"]),
            ficha["bitrate_num"],
            -ficha["profundidad"],
            -len(ficha["file"]),
            -ficha["mtime"])


def ficha_de(path):
    t = read_tags(path)
    br = t.get("bitrate") or ""
    try:
        bitrate_num = int(str(br).split()[0])
    except (ValueError, IndexError):
        bitrate_num = 0
    try:
        mtime = os.path.getmtime(path)
        tam = os.path.getsize(path)
    except OSError:
        mtime, tam = 0, 0
    return {
        "path": path,
        "file": os.path.basename(path),
        "carpeta": os.path.dirname(path),
        "profundidad": path.count(os.sep),
        "tags": [x for x in (t.get("genre") or "").replace("/", ";").split(";")
                 if x.strip()],
        "genre": t.get("genre") or "",
        "artist": t.get("artist") or "",
        "title": t.get("title") or "",
        "duration": t.get("duration") or "",
        "bitrate": br,
        "bitrate_num": bitrate_num,
        "bpm": t.get("bpm") or "",
        "key": t.get("key") or "",
        "cover": t.get("cover") or "",
        "tam": tam,
        "mtime": mtime,
    }


# ---------------------------------------------------------------------- estado

class Estado(object):
    def __init__(self):
        self.carpetas = []
        self.excluidas = []
        self.destino = ""
        self.estrategia = "fichero"     # "fichero" o "audio"
        self.grupos = []                # [{"id", "fichas", "master", "hecho"}]
        self.escaneando = False
        self.progreso = ""
        self.resumen = ""


E = Estado()


def destino_por_defecto():
    if E.destino:
        return E.destino
    if E.carpetas:
        return os.path.join(E.carpetas[0], NOMBRE_MASTERS)
    return os.path.expanduser("~/Music/" + NOMBRE_MASTERS)


def nombre_libre(carpeta, nombre):
    base, ext = os.path.splitext(nombre)
    i, cand = 2, nombre
    while os.path.exists(os.path.join(carpeta, cand)):
        cand = "%s (%d)%s" % (base, i, ext)
        i += 1
    return cand


# ------------------------------------------------------------------- escaneo

def _escanea_sync(carpetas, estrategia, destino, excluidas, avisa):
    rutas = ficheros_de_audio(carpetas, excluir=list(excluidas) + [destino])
    avisa("listando", len(rutas), len(rutas))
    crudos = agrupa_duplicados(rutas, estrategia, avisa)
    grupos = []
    for i, rutas_grupo in enumerate(crudos):
        fichas = sorted((ficha_de(r) for r in rutas_grupo),
                        key=puntua_master, reverse=True)
        grupos.append({"id": i, "fichas": fichas,
                       "master": fichas[0]["path"], "hecho": False})
    grupos.sort(key=lambda g: (-len(g["fichas"]), -g["fichas"][0]["tam"]))
    for i, g in enumerate(grupos):
        g["id"] = i
    return len(rutas), grupos


async def escanear():
    if E.escaneando:
        return
    if not E.carpetas:
        ui.notify("Añade al menos una carpeta que escanear", type="warning")
        return
    E.escaneando = True
    E.grupos = []
    E.progreso = "empezando..."
    panel_resultados.refresh()
    barra_estado.refresh()

    marca = [time.monotonic()]

    def avisa(etapa, hechos, total):
        ahora = time.monotonic()
        if ahora - marca[0] > 0.3 or hechos >= total:
            marca[0] = ahora
            E.progreso = "%s: %d / %d" % (etapa, hechos, total)

    reloj = ui.timer(0.4, barra_estado.refresh)
    t0 = time.monotonic()
    try:
        total, grupos = await run.io_bound(
            _escanea_sync, list(E.carpetas), E.estrategia,
            destino_por_defecto(), list(E.excluidas), avisa)
    finally:
        reloj.cancel()
        E.escaneando = False

    E.grupos = grupos or []
    sobrantes = sum(len(g["fichas"]) - 1 for g in E.grupos)
    bytes_sobra = sum(f["tam"] for g in E.grupos for f in g["fichas"][1:])
    E.progreso = ""
    E.resumen = ("%d temas revisados · %d grupos duplicados · %d copias de "
                 "sobra · %s recuperables · %.1f s"
                 % (total, len(E.grupos), sobrantes, humano(bytes_sobra),
                    time.monotonic() - t0))
    barra_estado.refresh()
    panel_resultados.refresh()


# ------------------------------------------------------------------- acciones

def aplica_grupo(g, avisar=True):
    """Mueve la master al destino y manda las demas a la papelera."""
    if g["hecho"]:
        return False
    master = g["master"]
    destino = destino_por_defecto()
    try:
        os.makedirs(destino, exist_ok=True)
    except OSError as e:
        ui.notify("No se ha podido crear %s: %s" % (destino, e), type="negative")
        return False

    if os.path.dirname(os.path.abspath(master)) != os.path.abspath(destino):
        nombre = nombre_libre(destino, os.path.basename(master))
        try:
            import shutil
            shutil.move(master, os.path.join(destino, nombre))
            nuevo = os.path.join(destino, nombre)
        except Exception as e:                             # noqa: BLE001
            ui.notify("No se ha podido mover la master: %s" % e, type="negative")
            return False
    else:
        nuevo = master

    fallos = 0
    for f in g["fichas"]:
        if f["path"] == master:
            continue
        try:
            if send2trash is None:
                raise RuntimeError("falta send2trash")
            send2trash(f["path"])
            comp = os.path.join(os.path.dirname(f["path"]),
                                "._" + os.path.basename(f["path"]))
            if os.path.exists(comp):
                try:
                    os.remove(comp)
                except OSError:
                    pass
        except Exception:                                  # noqa: BLE001
            fallos += 1

    g["hecho"] = True
    g["destino_final"] = nuevo
    g["fallos"] = fallos
    if avisar:
        ui.notify("Master en %s%s" % (os.path.basename(destino),
                                      "" if not fallos
                                      else "  ·  %d no se pudieron tirar" % fallos),
                  type="positive" if not fallos else "warning")
    return True


def aplica_todos():
    pendientes = [g for g in E.grupos if not g["hecho"]]
    if not pendientes:
        ui.notify("No queda ningun grupo por resolver", type="warning")
        return
    hechos = sum(1 for g in pendientes if aplica_grupo(g, avisar=False))
    panel_resultados.refresh()
    barra_estado.refresh()
    ui.notify("%d grupos resueltos" % hechos, type="positive")


def pon_master(g, path):
    g["master"] = path
    panel_resultados.refresh()


def abre_en_finder(path):
    import subprocess
    subprocess.Popen(["open", "-R", path])


# ------------------------------------------------------------------ interfaz

def construye_navegador(dlg, nav):
    """Navegador de carpetas del dialogo de elegir. Separado para probarlo."""
    atajos = [("Casa", os.path.expanduser("~")),
              ("Musica", os.path.expanduser("~/Music")),
              ("Volumenes", "/Volumes")]
    with ui.row().classes("gap-2 items-center flex-wrap"):
        ui.label("ir a:").classes("text-xs text-grey-6")
        for etiqueta, ruta in atajos:
            if os.path.isdir(ruta):
                ui.button(etiqueta, on_click=lambda r=ruta: navega(r)
                          ).props("outline dense no-caps").classes("text-xs")

    @ui.refreshable
    def navegador():
        actual = nav["dir"]
        with ui.row().classes("items-center gap-0 flex-wrap mt-1"):
            ui.button(icon="arrow_upward",
                      on_click=lambda: navega(os.path.dirname(actual))
                      ).props("flat dense round").classes("mr-2")
            acum = ""
            for parte in actual.strip("/").split("/"):
                acum += "/" + parte
                ui.button(parte, on_click=lambda r=acum: navega(r)
                          ).props("flat dense no-caps").classes("text-xs px-1")
                ui.label("/").classes("text-grey-7 text-xs")

        with ui.column().classes("w-full gap-0 overflow-auto mt-1").style(
                "max-height:44vh"):
            hijos = subcarpetas(actual)
            if not hijos:
                ui.label("(sin subcarpetas)").classes("text-grey-6 text-sm p-2")
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
                    ui.button(icon="check_circle",
                              on_click=lambda r=h: dlg.submit(r)
                              ).props("flat dense round color=positive")

        ui.separator().classes("mt-2")
        with ui.row().classes("w-full items-center gap-2 mt-2"):
            campo = ui.input(value=actual).props("dense outlined").classes(
                "flex-grow")
            campo.on("keydown.enter", lambda: navega(
                os.path.abspath(os.path.expanduser(campo.value))))
            ui.button("Cancelar", on_click=lambda: dlg.submit(None)).props("flat")
            ui.button("Usar esta carpeta",
                      on_click=lambda: dlg.submit(nav["dir"])
                      ).props("no-caps color=positive")

    def navega(ruta):
        if ruta and os.path.isdir(ruta):
            nav["dir"] = ruta
            navegador.refresh()

    navegador()


async def elige_carpeta(titulo, inicio):
    nav = {"dir": inicio if inicio and os.path.isdir(inicio)
           else os.path.expanduser("~")}
    with ui.dialog().props("persistent") as dlg, \
            ui.card().classes("w-[900px] max-w-full"):
        ui.label(titulo).classes("text-lg font-bold")
        construye_navegador(dlg, nav)
    ruta = await dlg
    dlg.delete()
    if not ruta:
        return None
    ruta = os.path.abspath(os.path.expanduser(ruta))
    return ruta if os.path.isdir(ruta) else None


async def anade_carpeta():
    r = await elige_carpeta("Carpeta que escanear",
                            E.carpetas[0] if E.carpetas else "")
    if r and r not in E.carpetas:
        E.carpetas.append(r)
        guarda_config()
        barra_carpetas.refresh()


async def cambia_destino():
    r = await elige_carpeta("Carpeta donde dejar las MASTER",
                            destino_por_defecto())
    if r:
        E.destino = r
        guarda_config()
        barra_carpetas.refresh()


def quita_carpeta(c):
    if c in E.carpetas:
        E.carpetas.remove(c)
        guarda_config()
        barra_carpetas.refresh()


async def anade_excluida():
    r = await elige_carpeta("Carpeta que NO quieres escanear",
                            E.carpetas[0] if E.carpetas else "")
    if r and r not in E.excluidas:
        E.excluidas.append(r)
        guarda_config()
        barra_carpetas.refresh()


def quita_excluida(c):
    if c in E.excluidas:
        E.excluidas.remove(c)
        guarda_config()
        barra_carpetas.refresh()


@ui.refreshable
def barra_carpetas():
    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
        ui.label("CARPETAS QUE ESCANEAR").classes(
            "text-xs font-bold text-grey-6")
        for c in E.carpetas:
            with ui.row().classes("items-center gap-1 bg-grey-9 rounded px-2"):
                ui.label(os.path.basename(c) or c).classes("text-xs").tooltip(c)
                ui.button(icon="close", on_click=lambda r=c: quita_carpeta(r)
                          ).props("flat dense round size=xs")
        ui.button("+ Añadir", on_click=anade_carpeta
                  ).props("outline dense no-caps").classes("text-xs")
        if not E.carpetas:
            ui.label("ninguna todavia").classes("text-xs text-orange")

    with ui.row().classes("w-full items-center gap-2 flex-wrap mt-1"):
        ui.label("EXCLUIR ESTAS").classes("text-xs font-bold text-grey-6")
        for c in E.excluidas:
            with ui.row().classes("items-center gap-1 bg-grey-9 rounded px-2"):
                ui.icon("block").classes("text-orange-6 text-xs")
                ui.label(os.path.basename(c) or c).classes("text-xs").tooltip(c)
                ui.button(icon="close", on_click=lambda r=c: quita_excluida(r)
                          ).props("flat dense round size=xs")
        ui.button("+ Excluir carpeta", on_click=anade_excluida
                  ).props("outline dense no-caps").classes("text-xs")
        ui.label("se salta la carpeta y todo lo que tenga dentro"
                 ).classes("text-xs text-grey-6")

    with ui.row().classes("w-full items-center gap-2 mt-1"):
        ui.label("LAS MASTER VAN A").classes("text-xs font-bold text-grey-6")
        ui.label(destino_por_defecto()).classes("text-xs text-green-4 truncate")
        if not E.destino:
            ui.label("(por defecto)").classes("text-xs text-grey-6")
        ui.button("Cambiar", on_click=cambia_destino
                  ).props("flat dense no-caps").classes("text-xs")


@ui.refreshable
def barra_estado():
    with ui.row().classes("w-full items-center gap-3"):
        ui.toggle({"fichero": "fichero idéntico", "audio": "mismo audio"},
                  value=E.estrategia,
                  on_change=lambda e: (setattr(E, "estrategia", e.value),
                                       guarda_config())
                  ).props("dense no-caps size=sm")
        ui.button("Buscar duplicados", on_click=escanear,
                  icon="search").props("no-caps color=primary").set_enabled(
            not E.escaneando)
        if E.escaneando:
            ui.spinner(size="sm")
            ui.label(E.progreso).classes("text-xs text-grey-5")
        ui.space()
        if E.grupos:
            pendientes = sum(1 for g in E.grupos if not g["hecho"])
            ui.button("Aplicar los %d grupos pendientes" % pendientes,
                      on_click=aplica_todos).props("no-caps color=positive"
                                                   ).set_enabled(pendientes > 0)
    if E.resumen:
        ui.label(E.resumen).classes("text-xs text-grey-5")


@ui.refreshable
def panel_resultados():
    if E.escaneando:
        ui.label("Buscando...").classes("text-grey-5")
        return
    if not E.grupos:
        ui.label("Sin resultados todavia. Añade carpetas y pulsa "
                 "«Buscar duplicados»." if not E.resumen
                 else "No hay duplicados con este criterio."
                 ).classes("text-grey-5 p-4")
        return

    for g in E.grupos:
        fichas = g["fichas"]
        cab = fichas[0]
        with ui.card().classes("w-full mb-3" + (" opacity-50" if g["hecho"]
                                                else "")):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.badge("%d copias" % len(fichas), color="orange")
                ui.label("%s — %s" % (cab["artist"] or "(sin artista)",
                                      cab["title"] or cab["file"])
                         ).classes("font-bold truncate")
                ui.label("%s · %s · %s" % (humano(cab["tam"]),
                                           cab["duration"] or "?",
                                           cab["bitrate"] or "?")
                         ).classes("text-xs text-grey-5")
                ui.space()
                if g["hecho"]:
                    ui.badge("resuelto", color="green")
                else:
                    ui.button("Aplicar",
                              on_click=lambda gg=g: (aplica_grupo(gg),
                                                     panel_resultados.refresh(),
                                                     barra_estado.refresh())
                              ).props("dense no-caps color=positive")

            if g["hecho"]:
                ui.label("master: %s" % g.get("destino_final", "")
                         ).classes("text-xs text-green-4 break-all")
                continue

            for f in fichas:
                es_master = f["path"] == g["master"]
                with ui.row().classes(
                        "w-full items-start gap-2 no-wrap px-2 py-1 rounded "
                        + ("bg-green-10" if es_master else "hover:bg-grey-9")):
                    ui.radio(["x"], value="x" if es_master else None,
                             on_change=lambda _e, gg=g, p=f["path"]:
                             pon_master(gg, p)).props("dense").classes("mt-1")
                    with ui.column().classes("gap-0 min-w-0 flex-grow"):
                        ui.label(f["file"]).classes("text-sm truncate")
                        ui.label(f["carpeta"]).classes(
                            "text-xs text-grey-6 truncate")
                        detalle = []
                        if f["tags"]:
                            detalle.append("tags: " + "; ".join(f["tags"]))
                        if f["bpm"]:
                            detalle.append("%s BPM" % f["bpm"])
                        if f["key"]:
                            detalle.append(f["key"])
                        if f["cover"].startswith("si"):
                            detalle.append("caratula")
                        if detalle:
                            ui.label("  ·  ".join(detalle)).classes(
                                "text-xs text-grey-5 truncate")
                        ui.audio(f["path"]).classes("w-full mt-1").props(
                            "preload=none")
                    with ui.column().classes("gap-1 items-end shrink-0"):
                        if es_master:
                            ui.badge("MASTER", color=COLOR_MASTER)
                        ui.button(icon="folder_open",
                                  on_click=lambda p=f["path"]: abre_en_finder(p)
                                  ).props("flat dense round size=sm").tooltip(
                            "ver en Finder")


@ui.page("/")
def pagina():
    with ui.header().classes("items-center gap-4 py-2"):
        ui.label("MACETE").classes("text-lg font-bold tracking-widest")
        ui.label("duplicados").classes("text-xs opacity-70")
        ui.space()
        ui.label("las copias descartadas van a la papelera del sistema"
                 ).classes("text-xs opacity-70")

    with ui.column().classes("w-full p-4 gap-3"):
        barra_carpetas()
        barra_estado()
        panel_resultados()


def arranca():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    abrir = "--no-show" not in sys.argv
    cfg = lee_config()
    E.carpetas = cfg["carpetas"]
    E.excluidas = cfg["excluidas"]
    E.destino = cfg["destino"]
    E.estrategia = cfg["estrategia"]
    for a in args:
        ruta = os.path.abspath(os.path.expanduser(a))
        if os.path.isdir(ruta) and ruta not in E.carpetas:
            E.carpetas.append(ruta)
    if send2trash is None:
        print("AVISO: falta send2trash, no se podran tirar copias a la papelera")
    print("Macete listo. %d carpetas configuradas. Masters -> %s"
          % (len(E.carpetas), destino_por_defecto()))
    ui.run(title="Macete", port=PUERTO, dark=True, reload=False,
           show=abrir, favicon="🧹")


if __name__ in {"__main__", "__mp_main__"}:
    arranca()
