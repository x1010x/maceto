#!/usr/bin/env python3
"""
Maceto - lector de tags ID3 para carpetas de musica.

Uso:
    maceto_tags.py [CARPETA] [opciones]

Opciones:
    -r, --recursive     Entra en subcarpetas
    -j, --json          Salida en JSON
    -c, --csv FICHERO   Guarda un CSV
    -f, --full          Ficha completa de cada tema (en vez de tabla)
    -s, --sort CAMPO    Ordena por: file, artist, title, genre, bpm, key, year, duration
    -h, --help          Esta ayuda

Sin argumentos usa la carpeta actual y saca una tabla.
Copyright (C) 2026 Maceto contributors

Software libre bajo la Licencia Pública General GNU, versión 3 o
posterior. Se distribuye SIN NINGUNA GARANTÍA. Ver el fichero LICENSE
o <https://www.gnu.org/licenses/>.

"""

import csv
import json
import os
import sys

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3NoHeaderError
except ImportError:
    sys.exit(
        "Falta 'mutagen'. Arranca con maceto.command, que prepara el entorno,\n"
        "o instalalo a mano:  pip install mutagen"
    )

# Extensiones de audio que miramos
AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".aiff", ".aif", ".wav", ".ogg", ".opus", ".wma"}

# Frame ID3 -> nombre de campo que usamos nosotros
ID3_FRAMES = {
    "TIT2": "title",
    "TPE1": "artist",
    "TPE2": "albumartist",
    "TALB": "album",
    "TCON": "genre",
    "TRCK": "track",
    "TPOS": "disc",
    "TBPM": "bpm",
    "TKEY": "key",
    "TPUB": "label",
    "TCOM": "composer",
    "TSRC": "isrc",
    "TENC": "encoder",
    "TDRC": "date",
    "TYER": "date",       # ID3v2.3
    "TDOR": "orig_date",
}

# Orden en el que salen los campos en la ficha completa
FIELD_ORDER = [
    "file", "title", "artist", "albumartist", "album", "genre", "date",
    "orig_date", "track", "disc", "bpm", "key", "label", "composer", "isrc",
    "comment", "encoder", "duration", "bitrate", "samplerate", "channels",
    "cover", "size_mb",
]


def _fmt_bpm(valor):
    """124.000000 -> 124 ; 123.50 -> 123.5 ; lo raro se deja tal cual."""
    txt = str(valor or "").strip()
    try:
        f = float(txt)
    except ValueError:
        return txt
    return str(int(f)) if f == int(f) else f"{f:g}"


def _fmt_duration(seconds):
    if not seconds:
        return ""
    seconds = int(round(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def read_tags(path):
    """Lee los tags de un fichero y devuelve un dict con campos normalizados."""
    tags = {k: "" for k in FIELD_ORDER}
    tags["file"] = os.path.basename(path)
    tags["path"] = path
    try:
        tags["size_mb"] = round(os.path.getsize(path) / (1024 * 1024), 2)
    except OSError:
        tags["size_mb"] = ""

    try:
        audio = MutagenFile(path)
    except (ID3NoHeaderError, Exception) as e:  # noqa: BLE001
        tags["error"] = f"{type(e).__name__}: {e}"
        return tags

    if audio is None:
        tags["error"] = "formato no reconocido"
        return tags

    # --- Info tecnica (streaminfo) ---
    info = getattr(audio, "info", None)
    if info is not None:
        tags["duration"] = _fmt_duration(getattr(info, "length", 0))
        tags["duration_s"] = round(getattr(info, "length", 0) or 0, 2)
        br = getattr(info, "bitrate", None)
        tags["bitrate"] = f"{br // 1000} kbps" if br else ""
        sr = getattr(info, "sample_rate", None)
        tags["samplerate"] = f"{sr} Hz" if sr else ""
        tags["channels"] = getattr(info, "channels", "") or ""

    raw = audio.tags
    if raw is None:
        tags["error"] = "sin tags"
        return tags

    # --- Tags ID3 (mp3/aiff/wav) ---
    if hasattr(raw, "getall"):
        for frame_id, field in ID3_FRAMES.items():
            if tags.get(field):          # ya relleno (p.ej. TDRC gana a TYER)
                continue
            frames = raw.getall(frame_id)
            if frames:
                tags[field] = str(frames[0]).strip()

        comments = [str(c) for c in raw.getall("COMM") if str(c).strip()]
        if comments:
            tags["comment"] = " | ".join(dict.fromkeys(comments))

        pics = raw.getall("APIC")
        if pics:
            tags["cover"] = f"si ({pics[0].mime}, {len(pics[0].data) // 1024} KB)"
        else:
            tags["cover"] = "no"

        # TXXX: campos libres (Mixed In Key, Rekordbox, Beatport, energy...)
        extra = {}
        for frame in raw.getall("TXXX"):
            extra[frame.desc] = " / ".join(str(v) for v in frame.text)
        if extra:
            tags["extra"] = extra

    # --- Tags no-ID3 (flac/ogg = Vorbis, m4a = MP4) ---
    else:
        vorbis_map = {
            "title": "title", "artist": "artist", "albumartist": "albumartist",
            "album": "album", "genre": "genre", "date": "date", "bpm": "bpm",
            "initialkey": "key", "key": "key", "label": "label",
            "organization": "label", "composer": "composer", "isrc": "isrc",
            "tracknumber": "track", "discnumber": "disc", "comment": "comment",
        }
        mp4_map = {
            "\xa9nam": "title", "\xa9ART": "artist", "aART": "albumartist",
            "\xa9alb": "album", "\xa9gen": "genre", "\xa9day": "date",
            "tmpo": "bpm", "\xa9wrt": "composer", "\xa9cmt": "comment",
            "trkn": "track", "disk": "disc",
        }
        for k, v in raw.items():
            field = vorbis_map.get(k.lower()) or mp4_map.get(k)
            if field and not tags.get(field):
                val = v[0] if isinstance(v, list) and v else v
                tags[field] = str(val).strip()
        tags["cover"] = "si" if (raw.get("covr") or getattr(audio, "pictures", None)) else "no"

    tags["bpm"] = _fmt_bpm(tags["bpm"])
    return tags


def scan_folder(folder, recursive=False):
    """Recorre la carpeta y devuelve la lista de dicts de tags."""
    resultados = []
    if recursive:
        rutas = (
            os.path.join(root, f)
            for root, _dirs, files in os.walk(folder)
            for f in sorted(files)
        )
    else:
        rutas = (os.path.join(folder, f) for f in sorted(os.listdir(folder)))

    for ruta in rutas:
        nombre = os.path.basename(ruta)
        if nombre.startswith("._"):          # AppleDouble de macOS en exFAT/NTFS
            continue
        if os.path.splitext(nombre)[1].lower() not in AUDIO_EXTS:
            continue
        if not os.path.isfile(ruta):
            continue
        resultados.append(read_tags(ruta))
    return resultados


def print_table(pistas):
    cols = [
        ("file", "FICHERO", 44),
        ("artist", "ARTISTA", 24),
        ("title", "TITULO", 28),
        ("genre", "GENERO", 15),
        ("bpm", "BPM", 6),
        ("key", "KEY", 4),
        ("date", "AÑO", 6),
        ("duration", "DUR", 7),
    ]

    def corta(txt, n):
        txt = str(txt or "")
        return txt if len(txt) <= n else txt[: n - 1] + "…"

    cab = "  ".join(f"{h:<{w}}" for _k, h, w in cols)
    print(cab)
    print("-" * len(cab))
    for p in pistas:
        fila = []
        for k, _h, w in cols:
            val = p.get(k, "")
            if k == "date":
                val = str(val)[:4]
            fila.append(f"{corta(val, w):<{w}}")
        print("  ".join(fila))


def print_full(pistas):
    for i, p in enumerate(pistas, 1):
        print(f"\n[{i}/{len(pistas)}] {p.get('file')}")
        print("-" * 70)
        for campo in FIELD_ORDER:
            if campo == "file":
                continue
            val = p.get(campo, "")
            if val not in ("", None):
                print(f"  {campo:<12} : {val}")
        for campo, val in (p.get("extra") or {}).items():
            print(f"  TXXX:{campo:<7.7}: {val}")
        if p.get("error"):
            print(f"  {'error':<12} : {p['error']}")


def escribe_csv(pistas, destino):
    campos = FIELD_ORDER + ["duration_s", "path", "error"]
    with open(destino, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for p in pistas:
            w.writerow(p)
    print(f"\nCSV guardado en: {destino}")


def resumen(pistas):
    sin_tags = [p for p in pistas if not p.get("title") and not p.get("artist")]
    sin_bpm = [p for p in pistas if not p.get("bpm")]
    sin_key = [p for p in pistas if not p.get("key")]
    sin_genero = [p for p in pistas if not p.get("genre")]
    sin_cover = [p for p in pistas if p.get("cover") in ("no", "")]
    print(f"\n{len(pistas)} temas analizados")
    print(f"  sin titulo/artista : {len(sin_tags)}")
    print(f"  sin BPM            : {len(sin_bpm)}")
    print(f"  sin KEY            : {len(sin_key)}")
    print(f"  sin genero         : {len(sin_genero)}")
    print(f"  sin caratula       : {len(sin_cover)}")


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    carpeta, recursive, como_json, csv_out, full, orden = ".", False, False, None, False, None
    i = 0
    posicionales = []
    while i < len(argv):
        a = argv[i]
        if a in ("-r", "--recursive"):
            recursive = True
        elif a in ("-j", "--json"):
            como_json = True
        elif a in ("-f", "--full"):
            full = True
        elif a in ("-c", "--csv"):
            i += 1
            csv_out = argv[i] if i < len(argv) else "tags.csv"
        elif a in ("-s", "--sort"):
            i += 1
            orden = argv[i] if i < len(argv) else None
        elif a.startswith("-"):
            sys.exit(f"Opcion desconocida: {a}  (usa --help)")
        else:
            posicionales.append(a)
        i += 1

    if posicionales:
        carpeta = posicionales[0]
    carpeta = os.path.abspath(os.path.expanduser(carpeta))
    if not os.path.isdir(carpeta):
        sys.exit(f"No es una carpeta: {carpeta}")

    pistas = scan_folder(carpeta, recursive=recursive)
    if not pistas:
        sys.exit(f"No se han encontrado audios en: {carpeta}")

    if orden:
        def clave(p):
            v = p.get(orden, "")
            if orden in ("bpm", "duration"):
                try:
                    return (0, float(p.get("duration_s") if orden == "duration" else v))
                except (TypeError, ValueError):
                    return (1, 0.0)
            return (0, str(v).lower())
        pistas.sort(key=clave)

    if como_json:
        print(json.dumps(pistas, ensure_ascii=False, indent=2))
    elif full:
        print_full(pistas)
    else:
        print(f"\n{carpeta}\n")
        print_table(pistas)

    if csv_out:
        escribe_csv(pistas, os.path.abspath(os.path.expanduser(csv_out)))
    if not como_json:
        resumen(pistas)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
