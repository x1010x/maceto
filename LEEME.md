# Maceto  ·  Macete

Dos programas hermanos:

- **Maceto** organiza la música por género y le escribe los tags.
- **Macete** busca canciones duplicadas y te deja quedarte con una.

Usan puertos distintos, así que puedes tenerlos abiertos a la vez.

---

# Maceto

Organizador de música por género. Te va pasando tema a tema por una carpeta,
te dice qué género lleva en el tag, te deja escucharlo y lo archiva de un clic
en la carpeta de género que le digas.

---

## Qué necesitas

- **Python 3.10 o superior.** En Mac: `brew install python`, o desde
  <https://www.python.org/downloads/>.
- Nada más. Lo demás se instala solo la primera vez, dentro de la propia
  carpeta de Maceto. No toca tu sistema.

## Arrancarlo

**Mac:** doble clic en `maceto.command`.
La primera vez tarda un minuto preparando el entorno; las siguientes, un segundo.

Si macOS se queja de que viene de un desarrollador no identificado: clic derecho
sobre `maceto.command` → **Abrir** → **Abrir**. Sólo hace falta la primera vez.

**Desde el terminal** (Mac o Linux):

```sh
./maceto.command                 # usa la última carpeta que abriste
./maceto.command /ruta/a/carpeta # o le dices cuál
```

**Windows:**

```
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python maceto.py
```

Se abre solo en el navegador, en <http://localhost:8099> (si ese puerto
te lo ocupa otro programa, arráncalo con `MACETO_PUERTO=8100 ./maceto.command`). Para cerrarlo, Ctrl+C
en la ventana del terminal.

## La primera vez

Te saldrá el panel de **Ajustes** para que le digas dónde tienes la música:

1. **Elegir carpeta...** → la carpeta que contiene tus árboles de clasificación.
   Por ejemplo, si tienes `Musica/ELECTRONICA/HOUSE`, `Musica/ELECTRONICA/TECHNO`,
   `Musica/ROCK/PUNK`… la carpeta a elegir es `Musica`.
2. **Solo las que contengan** → un filtro opcional, por si dentro de esa carpeta
   hay cosas que no quieres. Viene vacío, que significa *todas*. Aguanta erratas:
   si escribes `EXPERIENCE` también encuentra una carpeta llamada `EXPERENCE`.
3. Marca los árboles que quieras usar y dale a **Guardar**.

**Cada carpeta es un subgénero, sin límite de niveles.** Una canción en
`PSYCHEDELIC EXPERIENCE/PSYTRANCE/Hi Tech/tema.mp3` pertenece a los tres, y sus
tags serán esos tres.

Se guarda en `~/.maceto.json`. Puedes volver a Ajustes cuando quieras.

## Cómo se usa

- **Izquierda:** la cola de temas, **entrando en las subcarpetas** de la carpeta
  de origen (se puede desactivar). Debajo de cada nombre ves su subcarpeta, y a
  la derecha cuántos tags tiene ya. Salen primero **los que ya están etiquetados**
  y después los que no; el interruptor `por carpeta` cambia el orden. Pincha
  cualquiera para ir a él. Los que ya has archivado desaparecen de la lista;
  desmarca *ocultar los ya archivados* si quieres volver a verlos. El botón ↻
  vuelve a leer la carpeta desde el disco, por si has movido cosas por fuera.
- **Ficha:** carátula, título, artista y el género, BPM, tonalidad, duración y
  bitrate. Si no tiene género, el aviso sale en naranja.
- **Buscar el género en Chosic:** abre <https://www.chosic.com/music-genre-finder/>
  en otra pestaña con el tema ya en la URL. Si la web ignora el parámetro, el
  botón de al lado te copia «artista título» al portapapeles para que lo pegues
  en su buscador con Cmd+V.
- **Reproductor:** con barra de seek y volumen. Escúchalo antes de decidir.
  Cada tema carga su propio reproductor, y el volumen que dejes puesto se
  mantiene al pasar al siguiente.
- **Coincidencias:** las carpetas que casan con el tag de género, marcadas como
  `exacta`, `contiene` o `parecida`, con cuántos temas tiene ya cada una. Si el
  tema no tiene género, busca pistas en el nombre del fichero y te lo dice.
- **Atajos:** deducidos del nombre de la carpeta de origen. Si la carpeta se
  llama "Sesión Deep House / Tech House", te saca esas dos de un botón.
- **Árbol:** todas tus carpetas de destino con el número de temas de cada una,
  **ordenadas de más llena a más vacía**. El interruptor `nº temas / A-Z` cambia
  el criterio, y el buscador filtra.
- **Crear carpetas de género, por tres caminos:**
  - Si el tema trae un género que todavía no tiene carpeta, sale un botón
    `+ Crear la carpeta "LO QUE SEA"` directamente en las coincidencias.
  - Si buscas en el árbol algo que no existe, te ofrece crearlo con ese nombre.
  - `Carpeta nueva...` en el pie, para cualquier otro caso.

  En los tres casos eliges dentro de qué raíz va, y la carpeta recién creada
  queda ya seleccionada como destino.

**Teclado:** `Intro` mueve · `→` o `n` salta · `C` crea carpeta · `Cmd+Z` deshace.

## Etiquetar por carpetas

La idea: **la ruta de una canción ya dice a qué géneros pertenece**, así que
Maceto la convierte en tags.

- **Uno por uno:** en la ficha de cada tema, debajo de los tags que ya tiene,
  aparecen en gris los que salen de sus carpetas y un botón *añadir a este tema*.
- **De golpe:** el botón **Etiquetar carpeta...** del pie recorre la carpeta de
  origen entera, incluidas las subcarpetas, y te enseña antes de tocar nada:
  - todos los tags que ha detectado,
  - el desglose carpeta por carpeta, con cuántas canciones hay en cada una,
  - un campo para **añadir más tags** tuyos, que se aplican a todas
    (sepáralos con `;`),
  - una casilla para **borrar los tags que ya tengan** y dejar sólo estos.

  Sin marcar esa casilla, los tags nuevos se suman a los que hubiera, sin
  repetir. Mayúsculas y acentos no cuentan para decidir si un tag está repetido.

Los tags se guardan en el campo de **género**, todos juntos separados por `; `,
que es como lo leen Rekordbox, Serato y VirtualDJ.

## Cosas que conviene saber

- **Al mover, sumar el tag de la carpeta** (casilla del pie, activada): al
  archivar un tema en `TECH HOUSE` le añade ese tag. **Suma, no reemplaza**: los
  tags que ya tuviera se conservan. Desmárcala si prefieres no tocar los ficheros.
  Respeta la versión de ID3 que ya tuviera el fichero; si no tenía tags, crea
  una cabecera v2.3, que es la que mejor tragan los programas de DJ. El BPM, la
  tonalidad y la carátula no se tocan.
- **Deshacer** devuelve el tema a su sitio y además le deja exactamente los
  tags que tenía antes.
- Si en el destino ya hay un fichero con ese nombre, te enseña los dos con su
  duración, bitrate, BPM y tamaño, **y un reproductor para cada uno**, y decides
  tú: saltar, renombrar o sobrescribir.
- En discos exFAT, macOS deja un fichero `._loquesea.mp3` al lado de cada tema.
  Maceto los ignora y se los lleva junto al tema cuando lo mueve.
- Mueve, no copia. Y sólo dentro de lo que tú le marques.

---

# Macete — duplicados

Busca canciones repetidas en las carpetas que le digas y, por cada grupo, tú
eliges cuál es la **MASTER**.

**Arrancarlo:** doble clic en `macete.command`, o `./macete.command` desde el
terminal. Se abre en <http://localhost:8098> (Maceto usa el 8099, así que los
dos pueden estar abiertos). Para cambiar el puerto,
`MACETE_PUERTO=8100 ./macete.command`.

## Cómo se usa

1. **Carpetas que escanear:** añade una o varias. Mira dentro de todas sus
   subcarpetas.
2. **Excluir estas:** las carpetas que no quieres que toque. Se salta la
   carpeta y todo lo que tenga dentro.
3. **Las master van a:** la carpeta donde acabarán las elegidas. Si no pones
   ninguna, usa `_MACETE MASTERS` dentro de la primera carpeta escaneada — así
   el movimiento es instantáneo, al ser el mismo disco. Esa carpeta se excluye
   sola del escaneo.
4. Elige el criterio y dale a **Buscar duplicados**.

## Los dos criterios

- **Fichero idéntico** (por defecto): mismo tamaño y mismo contenido, byte a
  byte. Es el criterio seguro: si salen agrupadas, son la misma copia.
- **Mismo audio:** compara sólo los bytes de sonido, saltándose las etiquetas.
  Encuentra la misma canción aunque tenga distinto título, género o carátula, y
  por tanto distinto tamaño de fichero. Encuentra más, y sigue sin dar falsos
  positivos: el audio es idéntico o no lo es.

Para no leer de más va en tres pasos: primero compara tamaños, luego un trozo
del principio y del final, y sólo entonces el fichero entero. En una biblioteca
grande, la mayoría se descarta en el primer paso.

*Todavía no busca* canciones parecidas pero no idénticas — otra masterización,
otro bitrate, la misma canción en directo. Eso necesita una huella acústica y
es el siguiente paso.

## Elegir la master

Cada grupo te enseña todas las copias con su carpeta, tags, BPM, tonalidad,
bitrate y si tiene carátula, **y un reproductor para cada una**. Viene
preseleccionada la que tiene más tags, y a igualdad, mejor bitrate y ruta más
corta. Cámbiala si quieres.

**Aplicar** hace dos cosas:

- la master **se mueve** a tu carpeta de masters,
- las demás copias van a **la papelera del sistema**.

Van a la papelera, no se borran: si te equivocas, las recuperas desde Finder.
Ojo con una cosa: en discos externos la papelera vive en el propio disco
(`.Trashes`), así que hasta que la vacíes siguen ocupando espacio.

`Aplicar los N grupos pendientes` hace lo mismo con todos de golpe, cada uno con
la master que tenga marcada en ese momento.

---

# Detección de género en local (opcional)

Maceto puede decirte a qué suena una canción **sin internet y sin límite de
usos**, analizando el audio en tu ordenador.

Usa [Essentia](https://essentia.upf.edu/), del Music Technology Group de la
Universitat Pompeu Fabra de Barcelona, con su modelo entrenado sobre la
taxonomía de 400 estilos de Discogs. Es el mismo tipo de motor que hay detrás de
los detectores web, pero corriendo aquí.

**Instalarlo:** doble clic en `instalar_deteccion.command`. Baja unos 530 MB una
sola vez; a partir de ahí no vuelve a necesitar internet.

Necesita un Python **entre 3.9 y 3.12** (Essentia no publica versiones para
3.13+ todavía). En Mac suele valer el del sistema, así que normalmente no hay
que instalar nada más. El instalador lo busca solo.

**Cómo va:** unos 3 segundos por canción. El primer análisis de cada sesión
tarda un poco más porque carga los modelos; después el proceso se queda vivo.

**Qué tal acierta.** Sobre una biblioteca real de casa:

| canción | carpeta donde estaba | qué dijo |
|---|---|---|
| Crusy - Karma | TECH HOUSE | House 34% · Electro House 15% · **Tech House 15%** |
| (un psytrance) | PSYTRANCE | Tech Trance 39% · **Psy-Trance 31%** · Trance 28% |
| Aaron Sevilla - Mi Ritmo | TRIBAL HOUSE | Progressive House 31% · **Tribal House 31%** |
| Triana - Abre la puerta niña | FLAMENCO | Psychedelic Rock 15% · Prog Rock 14% · **Flamenco 8%** |

Va muy fino con la electrónica. Con mezclas raras se pone creativo: en el Triana
dijo rock psicodélico antes que flamenco, y no le falta razón, que eso es rock
andaluz. **Tú decides qué tag se queda**; el modelo sólo propone.

*No* identifica la canción ni la busca en ninguna base de datos: escucha el
audio y lo clasifica. Da igual cómo se llame el fichero o qué tags tenga.

## Extra: leer tags desde el terminal

`maceto_tags.py` lista los tags de una carpeta sin abrir la interfaz:

```sh
.venv/bin/python maceto_tags.py /ruta/a/carpeta            # tabla
.venv/bin/python maceto_tags.py /ruta -s bpm               # ordenado por BPM
.venv/bin/python maceto_tags.py /ruta -c tags.csv          # exporta a CSV
.venv/bin/python maceto_tags.py /ruta -f                   # ficha completa
.venv/bin/python maceto_tags.py /ruta -j                   # JSON
.venv/bin/python maceto_tags.py /ruta -r                   # con subcarpetas
```

Al final te dice cuántos temas van sin género, sin BPM, sin tonalidad o sin
carátula. Lee MP3, FLAC, M4A, AIFF, WAV, OGG y OPUS.
