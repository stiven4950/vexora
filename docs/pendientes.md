# Mejoras pendientes

Lo que se sabe que mejoraría la identificación y la edición, en orden de impacto. Cada punto dice
qué problema resuelve, qué se observó y qué haría falta.

## 1. Detector de hojas entrenado (espadas, bastones, katanas)

**Problema.** La detección clásica (`analysis/blades.py`) encuentra la hoja cuando está separada
del cuerpo, pero se confunde con rayas del piso, bordes de brazos y ropa. En video_1 (sin armas)
da "líneas" en el 78% de las manos, así que no puede decidir sola si hay una espada.

**Qué hacer, de menor a mayor esfuerzo:**

1. **YOLO-World** (integrado y **medido: no mejora**): `analysis.blades.detector: yoloworld`,
   requiere `pip install -e ".[objects]"`. En video_39, con el modelo grande (`yolov8x-worldv2`,
   1280 px, palabras "sword", "blade", "metal rod", "long thin metal pole") detecta hojas en 3 de
   8 fotogramas de muestra, y solo con las katanas quietas (4,4–5,8 s), donde la detección clásica
   ya acierta. En los giros, que es donde fallamos, no ve nada. Como respaldo de la detección
   clásica: 63% de hojas bien ubicadas, igual que sin él. Con "sword/katana/stick/lightsaber":
   1 de 8. Queda apagado.
1b. **Grounding DINO** (`IDEA-Research/grounding-dino-base`, medido con `tools/blade_eval.py`
   en video_39, 132 fotogramas, prompt "a sword. a katana. a metal blade."):

   | Detector | Hojas | Fotogramas con hoja | Bien ubicadas |
   | --- | --- | --- | --- |
   | Clásico (actual) | 194 | 123 | 63% |
   | Grounding DINO solo (diagonal de la caja) | 123 | 90 | 61% |
   | Clásico + DINO de respaldo | 219 | 127 | 63% |
   | Clásico filtrado por las cajas de DINO | 122 | 93 | **71%** |

   Como filtro sube la precisión 8 puntos pero pierde un cuarto de las hojas, y cuesta ~2,4 s por
   fotograma en MPS (~35 min para un video de 28 s). Mejora modesta: no se integra en el
   pipeline. Sí es útil como pre-etiquetador de cajas para el modelo propio (punto 2).

2. **Modelo propio de puntos clave**: etiquetar 300–500 fotogramas con empuñadura y punta
   (CVAT o Label Studio) y entrenar un YOLO-pose pequeño de dos puntos. Es la solución estable;
   también resuelve "¿hay espada en este video?".

   **Hecho:** sistema completo en `training/` (`vfxglow-train`). Primera prueba sin revisar:
   no generaliza a video_39 (detalle en training/README.md). Falta material variado.

   **Etiquetas casi gratis:** cada par original/referencia (`glowing/data/original` y
   `glowing/data/glowing`) ya trae la hoja pintada por un editor. La diferencia entre los dos
   fotogramas aísla el trazo de la hoja; su eje da empuñadura y punta. Con video_38 y video_39
   salen ~490 fotogramas etiquetados sin trabajo manual (revisando a ojo los dudosos), y cada
   referencia nueva suma más. Es el camino con más impacto medido por delante.
3. **Segmentación con SAM 2** a partir de la caja de YOLO-World: da la hoja completa aunque esté
   curvada o desenfocada. Requiere CUDA.

**Medido (2026-10-07)** contra lo pintado en las referencias, sobre los originales: video_38
(bastones con luz de fondo) 99% de hojas bien ubicadas; video_39 (katanas plateadas, cámara en
mano, volteretas) 63%. Los fallos de video_39 son hojas plateadas sobre el piso gris, hojas en
escorzo hacia la cámara y desenfoque de movimiento en los giros. El tajo de fuego del segundo
0,5 y las nubes de humo dependen de ver la hoja en ese instante, y ahí es donde más falla.

## 2. Saber de qué tipo es el video

**Problema.** Hoy el usuario elige el catálogo (`--catalog pelea`, `espadas_fuego`...).

**Qué hacer.** El lector de escena (gpt-5-mini) ya describe cada tramo. Pedirle además el tipo
(`pelea_mano`, `espadas_solo`, `espadas_duelo`, `baile`, `maquillaje`) y lo que cada persona tiene
en las manos, y elegir el catálogo y `needs` solos. Si el cliente indica el tipo, gana lo suyo.

## 3. Más de dos personas

**Problema.** El seguimiento admite dos personas (casillas `person_0`/`person_1`, por color del
torso). Una pelea de grupo o un público al fondo rompe la asignación.

**Qué hacer.** Seguimiento multi-persona por apariencia (re-identificación) con un detector de
personas (YOLO) en lugar de MediaPipe Pose para encontrarlas.

## 4. Siluetas con oclusión y por persona

**Problema.** `body_contour` usa el Selfie Segmenter y se queda con la silueta más grande: con
dos personas pegadas sale una sola mancha, y con el público al fondo puede tomar a otra persona.

**Qué hacer.** Máscara por persona (SAM 2 con la caja de cada persona, nivel `masks`, CUDA) o el
segmentador multiclase recortado a la caja de cada pose.

## 5. Piso y profundidad

**Problema.** El piso se estima con el tobillo más bajo del fotograma. Las salpicaduras y la
nube de humo se aplanan con un factor fijo (0,32), sin conocer la perspectiva real.

**Qué hacer.** Estimar el plano del suelo (horizonte + líneas del piso, o un modelo de
profundidad monocular como Depth Anything) para que los efectos del suelo sigan la perspectiva
y queden detrás de los pies.

## 6. Rendimiento

**Problema.** Renderizar 28 s tarda ~6 min en CPU (Skia + NumPy por efecto y fotograma).

**Qué hacer.** Dibujar todos los efectos de un fotograma en una sola superficie de Skia, cachear
las capas estáticas y paralelizar por tramos. Objetivo: tiempo real ×0,5 en CPU.

## 7. Calidad del tracking en acrobacias

**Problema.** En volteretas MediaPipe pierde o invierte la pose (video_39 2,2–3,5 s), y con ella
anclas, eventos y siluetas.

**Qué hacer.** Modelo de pose más robusto para acrobacias (RTMPose/RTMW, ya previsto en el nivel
`hq`) y relleno temporal más largo cuando la persona está en el aire.

## 8. Efectos vistos en referencias y aún no hechos

| Efecto | Dónde | Qué falta |
| --- | --- | --- |
| Venas de energía dentro del cuerpo | video_38 10,4 s | Rayos fractales recortados al contorno |
| Puños en llamas antes de golpear | video_1 19,5 s | Contorno de la mano con lenguas de fuego |
| Rayos que recorren el brazo al agarrar | video_1 4,3 s | Evento de agarre + rayo sobre la cadena del brazo |
| Remolino de aturdimiento | video_1 10,4 s | Evento "recibe golpe y se tambalea" |
| Onda elíptica en el suelo al pisar | video_1 13,5 s | `foot_strike` + elipse con perspectiva (punto 5) |
| Aura de cuerpo en guardia | video_1 7,2 s | Contorno desplazado en capas alrededor de la silueta |
| Llamas sobre las cabezas en tensión | video_1 23,3 s | Evento de tensión (cerca y quietos) |
| Cintas en el cielo al cierre | video_1 26,8 s | Evento de cierre del video |
