# Arquitectura

El sistema compone. No traduce un video a otro. El fotograma original no entra en ningún generador. Cada efecto es geometría anclada al movimiento y sale como capa HDR con transparencia.

## Pipeline

```text
Video
  -> Análisis (pose, manos, cara, cinemática)
  -> tracks.jsonl + events.jsonl + motion_brief.json
  -> Director (preset o LLM) -> effect_script.json
  -> Motor procedural -> capas RGBA
  -> Refinador opcional, solo dentro de la máscara
  -> Composición lineal + copia de audio
  -> Video final
```

Cada etapa escribe en `runs/<id>/` y guarda una huella en `manifest.json`. Repetir el director o el motor no vuelve a analizar el video.

## Por qué esta división

Un Pix2Pix entrenado con pares de un solo video aprende esa traducción, no el efecto. Aquí el concepto del efecto vive en el guion (`type`, ancla, paleta, ruido temporal) y la coherencia entre fotogramas sale de datos filtrados, no de un modelo generativo:

- One Euro por punto, y Catmull-Rom solo en huecos cortos. Un hueco largo apaga esa ancla.
- Las cintas y los trails usan la historia ya filtrada (Catmull-Rom centrípeta).
- El ruido es 3D: la tercera coordenada es el tiempo y la semilla es fija.
- El refinador, si se enciende, deforma la textura anterior con flujo óptico y solo sustituye el color dentro del alfa.

## Análisis

`analysis.level` elige un backend. No se encadenan todos los modelos en cada video.

| Nivel | Cuándo | Tecnología |
| --- | --- | --- |
| `fast` | Por defecto. CPU y Apple Silicon. | MediaPipe Pose, Hands y Face. Las manos que el seguimiento pierde se buscan en un recorte alrededor de la muñeca. |
| `hq` | Cuerpo entero con manos pequeñas. Extra `hq`. | YOLO11 para la persona y objetos; RTMW vía rtmlib para 133 puntos. |
| `masks` | Aura u oclusión. Solo CUDA. | SAM 2.1, disparado por la caja de la pose. |

OpenPose y Detectron2 no son la base: pesan más y no mejoran manos ni instalación en macOS. El flujo óptico no sustituye a los landmarks. Farneback acompaña siempre que `analysis.flow.enabled` está activo; RAFT pequeño solo entra en CUDA si torchvision está instalado. Sirve para deformar la capa previa, no para seguir al actor.

MediaPipe sigue hasta dos personas (`num_poses: 2`) y les asigna `person_0` y `person_1` por solapamiento de la caja. El evento `person_contact` marca atacante y receptor cuando una muñeca alcanza el torso o la cabeza de la otra. `tool_touch` marca la mano que trabaja junto al rostro.

`analysis/beats.py` parte el clip en beats con PySceneDetect si está instalado y, si no, con un corte de histograma. Los onsets salen de librosa o del flujo espectral del audio. `analysis/appearance.py` guarda el contorno del pigmento activo, la punta de la herramienta y si los ojos del plano ya brillan. `analysis/scene_reader.py` pide a `gpt-5-mini` un JSON por beat cuando hay `OPENAI_API_KEY`; sin clave esa lectura queda vacía.

El brief no guarda los 478 puntos de la cara. Guarda velocidad, dirección, trayectoria simplificada, beats y un recuento de eventos. `EventDetector` marca swing, impacto, pie, contacto de mano, contacto entre personas, toque de herramienta, objeto sostenido, giro, salto, mano abierta/cerrada y brazos cruzados. Una muestra con velocidad imposible se marca `glitch` y no dispara nada.

Los objetos, si `ultralytics` está instalado, los sigue `ObjectTracker` (`analysis/objects.py`) con YOLO11n e IoU. `hq` ya no tiene su propio bucle YOLO.

## Director

`CreativeDirector` tiene dos salidas y un solo esquema Pydantic:

- `provider: preset` lee `configs/presets/<nombre>.yaml`.
- `provider: openai` o `anthropic` recibe el brief, las anclas, el catálogo de tipos y las estrategias aplicables. Puede devolver un Effect Script o un plan `{choices: [...]}` que `director/strategies.py` expande. Un JSON inválido se reintenta una vez.

El catálogo (`material_contour`, `tool_tip_flame`, `feature_lights`, `impact_accent`, `charge_up`, `debris_fall`, `limb_trace`, `character_overlay`, `symbol_react`, `motion_smear`, `silhouette_trace`, `beat_grade`) se combina por beat. Los presets `fight_comic`, `doodle_dance` y `paint_reveal` son expansiones fijas de ese catálogo. Los glifos viven en `assets/glyphs`; un SVG escrito por el modelo solo entra si usa `path`, `circle` o `line` y tiene menos de 40 elementos.

Tipos: `ribbon`, `trail`, `particles`, `aura`, `stroke`, `lightning`, `decal`, `distortion`, `cracks`, `ripples`, `charge`, `sparks`, `glyph`, `impact_accent`, `smear`, `silhouette`, `grade`, `contour`, `tip_flame`, `feature_light`. `triggers` vacíos: el intervalo `time` manda. Si hay triggers, solo se enciende con el evento. `event_point` fija el efecto al punto del contacto. Un efecto sin triggers no puede cruzar un beat `cut`. `beat_grade` no se solapa consigo mismo. El color de un `actor` no cambia entre efectos.

### Tipos como primitivas

El plan de mejoras habla de primitivas (`trace`, `glow`, `ring`…). Ya existen como tipos del guion; los presets son listas de ellas, no un catálogo cerrado.

| Primitiva | Tipo del guion |
| --- | --- |
| trace | `stroke`, `face_linework`, `drawing`, `contour`, `silhouette` |
| glow | bloom por grupo al componer; `feature_light`, `aura` |
| ring | `eye_rings` |
| arc | `smear`, `lightning` (con `secondary`) |
| burst | `impact_accent`, `glyph` |
| spark | `sparks` |
| particle | `particles` |
| trail | `trail`, `ribbon` |
| ripple | `ripples`, `cracks`, `charge` |

### Anclas

El guion nunca lleva coordenadas. `target.kind` + `target.id` se resuelven en cada fotograma (`engine/anchors.py`):

- `joint`: articulación de pose o mano (`right_wrist`, `left_ankle`, `nose`…), o `person_N:<articulación>` con dos personas.
- `chain`: cadena de articulaciones (`analysis/names.py: CHAINS`).
- `face_region`: rasgos de la malla (`eyes`, `lips`, `brows`, `oval`…) y puntos derivados (`left_iris`, `face_center`, `mouth_center`).
- `object`: `object:<id>`, `object:<clase>` u `object:any`.
- `event_point`: el punto donde ocurrió el evento que encendió el efecto.
- `contour` / `mask`: contorno del pigmento o máscara de persona.

Cambiar el perceptor solo exige producir los mismos nombres.

## Motor

El raster no es el origen de la calidad. Lo es el buffer lineal de energía.

- Geometría en NumPy: splines, normales, ruido, partículas, rayo fractal (`engine/lightning.py`) e interacción (`engine/interaction.py`).
- `ActivationTimeline` convierte eventos en envolvente con hold y cooldown.
- Persistencia: `layer + persist * decay` para la cola luminosa.
- Trazos en Skia. `line boil` (`style.boil_frames`) redibuja el trazo cada N fotogramas. El bloom multicapa ocurre al componer, por grupo (`grade`, `glow`, `particles`, `interaction`, `lightning`). `grade` se multiplica sobre el plano antes del glow.

El motor no abre el video. Lee tracks, el guion y el tamaño del cuadro. `render.occlude` recorta la capa con la máscara de persona erosionada, para que el fuego pueda quedar detrás del torso; sin máscara de SAM usa la persona de `analysis/regions.py`, con el borde suave. Esas etiquetas son la única excepción al "no abre el video": `Pipeline._engine` las calcula antes de renderizar si el guion las pide.

## Refinador

Apagado en `configs/default.yaml`. Encenderlo sin CUDA aborta al inicio. Con CUDA carga inpaint de Stable Diffusion y, si el ControlNet de pose está disponible, lo usa como condición. La máscara es el alfa dilatado de la capa procedural. Fuera de esa máscara el resultado se descarta. Los fotogramas clave se generan; los intermedios se obtienen deformando la textura anterior. Flux y los modelos de video completo quedan fuera: tienden a redibujar al sujeto.

## Composición

1. El plano pasa de sRGB a lineal. No hay denoise ni cambio de exposición.
2. Cada capa, en el orden de grupo: `multiply` tiñe el plano, `add` suma la energía premultiplicada, `screen` para halos, `over` para un decal que tapa.
3. Una rodilla suave comprime solo la energía del efecto por encima del umbral. Por debajo es identidad.
4. Donde la cobertura es nula, se restaura el plano bit a bit en luz lineal y se vuelve a sRGB.
5. ffmpeg escribe la imagen y copia el audio.

H.264 es el codec por defecto. `composite.codec: prores` pide ProRes 4444.

## Dispositivo

`cuda`, si no `mps`, si no `cpu`. MediaPipe usa su propio runtime. PyTorch solo hace falta para SAM 2.1, el refinador y RAFT, y esos tres exigen CUDA en este proyecto.
