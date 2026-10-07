# Entrenamiento de detectores propios

Sistema para entrenar detectores que el pipeline usa en el análisis. La primera tarea es `blade`
(hojas de espada, katanas, bastones); la misma estructura sirve para tareas futuras (otro objeto,
otra clase) con solo escribir un `training/tasks/<nombre>.yaml`.

## Estructura

```text
training/
  tasks/<tarea>.yaml          definición de la tarea (versionado)
  review/<tarea>/<fuente>/
    rejected.txt              etiquetas descartadas a mano (versionado: es trabajo humano)
    sheet_NN.jpg              hojas de revisión (generadas, no se versionan)
  data/                       descargas y etiquetas candidatas (no se versiona)
    openimages/               cajas filtradas e imágenes de Open Images
    labels/<tarea>/<fuente>/  <clave>.jpg + labels.jsonl
  datasets/<tarea>/           dataset YOLO armado (no se versiona)
  runs/<tarea>/               salida de Ultralytics: métricas, gráficas, pesos (no se versiona)
models/<tarea>-obb.pt         pesos exportados que usa el pipeline
src/vfxglow/training/         código
tools/blade_eval.py           medición contra lo pintado en una referencia
```

## Flujo

```bash
pip install -e ".[train]"

# 1. Etiquetas candidatas de todas las fuentes + hojas de revisión
vfxglow-train label --task training/tasks/blade.yaml
vfxglow-train label --task training/tasks/blade.yaml --only video_38      # una sola fuente

# 2. Revisión: abrir training/review/blade/<fuente>/sheet_*.jpg y copiar a
#    training/review/blade/<fuente>/rejected.txt la clave de cada mosaico mal etiquetado
#    (la que aparece arriba del mosaico).

# 3. Dataset (excluye lo rechazado) y entrenamiento (exporta a models/blade-obb.pt)
vfxglow-train build --task training/tasks/blade.yaml
vfxglow-train train --task training/tasks/blade.yaml

# 4. Medir contra la referencia que no se usó para entrenar (holdout)
python tools/blade_eval.py --run runs/video_39-9961beb5 --model models/blade-obb.pt \
  --original ../glowing/data/original/video_39.mp4 --reference ../glowing/data/glowing/video_39.mp4

# 5. Usarlo en el pipeline: configs/default.yaml -> analysis.blades.detector: model
```

## Fuentes de etiquetas

| Fuente | Cómo se etiqueta | Revisión |
| --- | --- | --- |
| `pairs`: original + versión con glow | La referencia se alinea con el original (ECC afín: puede venir reencuadrada) y sobre lo pintado se barre desde cada mano en busca de la franja recta. Se exige una cresta real en el original debajo y se descartan fotogramas con siluetas pintadas | Recomendada: ~la mitad sale bien |
| `openimages`: fotos con la clase `Sword` | Dentro de cada caja recta se busca la recta dominante; si la caja ya es alargada se usa tal cual | Recomendada |
| `videos`: video sin glow | Pre-etiquetado con el detector actual del pipeline | Obligatoria |

El video con glow **no se usa para entrenar**: solo sirve para saber dónde está la hoja en el
original. El modelo solo ve fotogramas originales.

## Decisiones

- **Cajas rotadas (YOLO-OBB), no "empuñadura y punta".** Una caja rotada no distingue extremos,
  así que sirve igual para una foto de una espada colgada. La empuñadura se decide en el pipeline,
  por cercanía a la mano.
- **Validación por video completo** (`holdout`): fotogramas de un mismo video en entrenamiento y
  validación serían casi idénticos y la medida saldría inflada.
- **Copias con desenfoque de movimiento** de cada imagen de entrenamiento: el caso que falla es la
  hoja girando rápido, y las fotos de Open Images son estáticas.

## Línea base (detector clásico, `tools/blade_eval.py` con alineación)

| Video | Hojas bien ubicadas |
| --- | --- |
| video_38 | 66% |
| video_39 (holdout) | 44% |

## Historial de entrenamientos

### blade, prueba 1 (2026-10-07) — no se usa

- Datos sin revisar: video_38 (45 fotogramas) + Open Images train (221 fotos) + copias con
  desenfoque. Validación: video_39 (18) + Open Images validation/test (73).
- yolo11n-obb, 960 px, 80 épocas en MPS: 1,4 h. Validación mAP50 0,42 (P 0,54, R 0,49).
- `tools/blade_eval.py` en video_39 (nunca visto): **0 hojas útiles** (detecta algo en 47 de 175
  fotogramas, casi todo falso; no ve ni las katanas quietas de 4,8–5,8 s). En video_38 (visto):
  80% de lo que detecta está bien, pero solo en 9 fotogramas.
- Diagnóstico: Open Images de espadas son 717 cajas en total (no "miles"), casi todas fotos de
  catálogo o museo con fondo blanco; y de video solo hay un clip de bastones. Nada se parece a una
  katana plateada en movimiento en un gimnasio. El sistema funciona de punta a punta; falta
  material. El pipeline sigue con `detector: lines`.
- Lo que haría falta para la prueba 2: varios videos de espadas variados (pares original/glow, o
  videos solos para pre-etiquetar y revisar), y revisar las etiquetas (`rejected.txt`).

## Tarea nueva

1. Copiar `tasks/blade.yaml` como `tasks/<nombre>.yaml` y cambiar `name`, `classes`, fuentes y
   la clase de Open Images (MID, ver `oidv7-class-descriptions-boxable.csv`).
2. Si las etiquetas salen de pares con otro tipo de efecto, añadir un extractor en
   `src/vfxglow/training/pairs.py` (`EXTRACTORS`) y nombrarlo en `pairs[].extractor`.
3. Mismo flujo `label → revisión → build → train`.
