#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Detector de genero de Maceto, en local y sin internet.

Usa los modelos del Music Technology Group de la UPF (Essentia + la taxonomia
de 400 estilos de Discogs), los mismos que hay detras de herramientas web como
la de SubmitHub, pero corriendo aqui y sin limite de usos.

Este fichero NO se ejecuta con el Python de Maceto: necesita el entorno
~/music-tools/.venv-ia, que lleva Python 3.9 porque las ruedas de Essentia para
macOS no llegan a 3.14.

Dos formas de usarlo:

    macetoia.py fichero.mp3 [otro.mp3 ...]     una tirada y a la calle
    macetoia.py --servidor                     lee rutas por la entrada
                                               estandar y escupe una linea
                                               JSON por cada una

El modo servidor es el que usa Maceto: carga los modelos una vez (tarda un par
de segundos) y ya responde en ~3 s por cancion.
Copyright (C) 2026 Maceto contributors

Software libre bajo la Licencia Pública General GNU, versión 3 o
posterior. Se distribuye SIN NINGUNA GARANTÍA. Ver el fichero LICENSE
o <https://www.gnu.org/licenses/>.

"""

import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELOS = os.path.join(AQUI, "modelos")
EMBEDDINGS = os.path.join(MODELOS, "discogs-effnet-bs64-1.pb")
CABEZA = os.path.join(MODELOS, "genre_discogs400-discogs-effnet-1.pb")
ETIQUETAS = os.path.join(MODELOS, "genre_discogs400-discogs-effnet-1.json")

MINIMO = 0.02          # por debajo de esto ni se menciona
CUANTOS = 8            # cuantos estilos como mucho


def limpia(etiqueta):
    """'Electronic---Tech House' -> ('Tech House', 'Electronic')."""
    if "---" in etiqueta:
        familia, estilo = etiqueta.split("---", 1)
        return estilo.strip(), familia.strip()
    return etiqueta.strip(), ""


class Detector(object):
    def __init__(self):
        for f in (EMBEDDINGS, CABEZA, ETIQUETAS):
            if not os.path.exists(f):
                raise SystemExit("Falta el modelo: %s" % f)
        # se importa aqui dentro para que el error de entorno salga claro
        import numpy
        from essentia.standard import (MonoLoader, TensorflowPredict2D,
                                       TensorflowPredictEffnetDiscogs)
        self.np = numpy
        self.cargador = MonoLoader
        with open(ETIQUETAS, encoding="utf-8") as fh:
            self.clases = json.load(fh)["classes"]
        self.embeddings = TensorflowPredictEffnetDiscogs(
            graphFilename=EMBEDDINGS, output="PartitionedCall:1")
        self.cabeza = TensorflowPredict2D(
            graphFilename=CABEZA,
            input="serving_default_model_Placeholder",
            output="PartitionedCall:0")

    def analiza(self, ruta):
        audio = self.cargador(filename=ruta, sampleRate=16000,
                              resampleQuality=4)()
        if len(audio) < 16000:
            return []
        medias = self.cabeza(self.embeddings(audio)).mean(axis=0)
        orden = self.np.argsort(medias)[::-1][:CUANTOS]
        salida = []
        for i in orden:
            p = float(medias[i])
            if p < MINIMO:
                continue
            estilo, familia = limpia(self.clases[i])
            salida.append({"estilo": estilo, "familia": familia,
                           "prob": round(p, 4)})
        return salida


def main(argv):
    silencia()
    servidor = "--servidor" in argv
    rutas = [a for a in argv if not a.startswith("-")]

    try:
        det = Detector()
    except SystemExit:
        raise
    except Exception as e:                                 # noqa: BLE001
        print(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}),
              flush=True)
        return 1

    if servidor:
        print(json.dumps({"listo": True}), flush=True)
        for linea in sys.stdin:
            ruta = linea.strip()
            if not ruta:
                continue
            if ruta == "__salir__":
                break
            try:
                print(json.dumps({"path": ruta, "generos": det.analiza(ruta)}),
                      flush=True)
            except Exception as e:                         # noqa: BLE001
                print(json.dumps({"path": ruta,
                                  "error": "%s: %s" % (type(e).__name__, e)}),
                      flush=True)
        return 0

    if not rutas:
        print(__doc__)
        return 0
    for ruta in rutas:
        try:
            print(json.dumps({"path": ruta, "generos": det.analiza(ruta)},
                             ensure_ascii=False), flush=True)
        except Exception as e:                             # noqa: BLE001
            print(json.dumps({"path": ruta, "error": str(e)}), flush=True)
    return 0


def silencia():
    """Essentia y TensorFlow escupen mucho ruido por la salida de error."""
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    try:
        import essentia
        essentia.log.infoActive = False
        essentia.log.warningActive = False
    except Exception:                                      # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
