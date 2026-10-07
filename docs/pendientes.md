# Mejoras pendientes

Lo que se sabe que mejoraría la identificación y la edición, en orden de impacto. Cada punto dice
qué problema resuelve, qué se observó y qué haría falta.

## 1. Detector de hojas entrenado (espadas, bastones, katanas)

**Problema.** La detección clásica (`analysis/blades.py`) encuentra la hoja cuando está separada
del cuerpo, pero se confunde con rayas del piso, bordes de brazos y ropa. En video_1 (sin armas)
da "líneas" en el 78% de las manos, así que no puede decidir sola si hay una espada.

**Qué hacer, de menor a mayor esfuerzo:**

1. **YOLO-World** (ya integrado, sin probar): `analysis.blades.detector: yoloworld`. Requiere
   `pip install -e ".[objects]"` (ultralytics, ~1 GB con torch). Detecta "sword", "katana",
   "stick" por texto, sin entrenar; da una caja y se usa la diagonal que pasa por la mano.
   Validar en video_39 4,4–5,8 s antes de confiar.
2. **Modelo propio de puntos clave**: etiquetar 300–500 fotogramas con empuñadura y punta
   (CVAT o Label Studio) y entrenar un YOLO-pose pequeño de dos puntos. Es la solución estable;
   también resuelve "¿hay espada en este video?".
3. **Segmentación con SAM 2** a partir de la caja de YOLO-World: da la hoja completa aunque esté
   curvada o desenfocada. Requiere CUDA.

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
