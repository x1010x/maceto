# Maceto · Macete

**Dos herramientas para ordenar una biblioteca de música grande, en tu Mac
y desde el navegador.** Sin subir nada a ninguna nube.

![Python](https://img.shields.io/badge/python-3.10+-3776ab)
![Licencia](https://img.shields.io/badge/licencia-GPL--3.0-green)
![macOS](https://img.shields.io/badge/macOS-lightgrey)

- 🎵 **Maceto** — recorre tu música tema a tema y la reparte en carpetas por
  género: te propone a dónde va cada canción según sus tags, te la deja
  escuchar antes de decidir, y mueve con un click.
- 🧹 **Macete** — encuentra las canciones **duplicadas**, las agrupa, y por
  cada grupo eliges cuál es la buena: esa se queda, las demás a la papelera.

Los dos se abren solos en el navegador (`localhost`), funcionan sin internet
y no tocan nada hasta que tú lo dices.

---

## Maceto — organizar por género

Le das una carpeta de origen y tu árbol de carpetas por género. Maceto va
tema a tema:

- Lee los **tags** de la canción y te propone a qué carpeta de destino mandarla.
- Te deja **escucharla** antes de decidir, con reproductor integrado.
- Si no lo tiene claro, puedes **elegir cualquier otra carpeta**, crear una
  nueva, o saltar el tema.
- **Deshace** lo último por si te equivocas.
- Filtra la cola por **cuántos tags tiene** cada tema (0 tags, 1, 2+): así
  atacas primero lo que te falta por etiquetar.
- Opcional: un botón **"Detectar género"** que usa un modelo de IA **local**
  (Essentia, del MTG de la UPF) para sugerir el género cuando la canción no
  trae tag. Sin internet, sin límite de usos.

## Macete — quitar duplicados

Le das las carpetas a escanear. Agrupa las canciones repetidas por dos
criterios (nombre o huella de audio), y por cada grupo eliges la **master**:
esa se mueve a tu carpeta de masters y las copias se van a la papelera del
sistema (recuperables). Usa otro puerto que Maceto, así que puedes tener los
dos abiertos a la vez.

## Instalación

Necesitas **Python 3.10+**. Los lanzadores preparan el entorno solos la
primera vez.

**En un comando:**

```bash
curl -fsSL https://raw.githubusercontent.com/x1010x/maceto/main/install-mac.sh | bash
```

Clona Maceto en `~/maceto`, prepara el entorno y te deja los lanzadores
listos. Pregunta si quieres también el detector de género por IA.

**O a mano:**

```bash
git clone https://github.com/x1010x/maceto.git
cd maceto
./maceto.command        # organizador por género  → http://localhost:8099
./macete.command        # buscador de duplicados   → otro puerto
```

En macOS también puedes hacer **doble clic** en `maceto.command` desde el
Finder. La primera vez crea un entorno virtual e instala las dependencias
(NiceGUI, mutagen, send2trash); después arranca en un segundo.

### Detección de género por IA (opcional)

Maceto funciona sin esto; solo que sin el botón "Detectar género". Si lo
quieres:

```bash
./instalar_deteccion.command
```

Baja los modelos de **Essentia** (del Music Technology Group de la UPF,
Barcelona) — unos 530 MB, una sola vez — y los deja corriendo en local. Son
los mismos modelos que hay detrás de herramientas web como la de SubmitHub,
pero aquí sin límite de usos y sin mandar tu música a ningún sitio.

## Extra: leer tags desde el terminal

`maceto_tags.py` es un lector de tags ID3 por línea de comandos:

```bash
python3 maceto_tags.py ~/Música -r            # recursivo, en tabla
python3 maceto_tags.py ~/Música -j            # salida JSON
python3 maceto_tags.py ~/Música -s bpm        # ordenado por BPM
```

## Ficheros

```
maceto/
├── maceto.py            # organizador por género (web)
├── macete.py            # buscador de duplicados (web)
├── maceto_tags.py       # lector de tags ID3 (CLI)
├── macetoia.py          # detector de género local (Essentia)
├── maceto.command       # lanzador de Maceto
├── macete.command       # lanzador de Macete
├── instalar_deteccion.command  # instala el detector de IA (opcional)
├── install-mac.sh       # instalador de una línea
├── requirements.txt
├── LEEME.md             # documentación detallada
├── LICENSE
└── modelos/             # (los baja el instalador; no van en git)
```

Para la guía completa de uso, mira [`LEEME.md`](LEEME.md).

## Licencia

GPL-3.0. Ver [LICENSE](LICENSE). Se distribuye sin ninguna garantía.

El detector de género usa modelos de [Essentia](https://essentia.upf.edu/)
(Music Technology Group, Universitat Pompeu Fabra), que tienen su propia
licencia y se descargan aparte.
