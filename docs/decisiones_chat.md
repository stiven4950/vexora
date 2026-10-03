Plan de mejoras — VFXGlow
3 oct 2026 · preparado por @Stiven
Contexto y objetivo
VFXGlow analiza un video, decide efectos por tramos (beats) y los dibuja como capas RGBA de luz encima del plano original, sin regenerar el fotograma. El objetivo de este plan no es agregar capacidades nuevas, sino consolidar lo que ya funciona (face_neon) y arreglar lo que ya se diagnosticó como roto, antes de evaluar cualquier herramienta externa con licencia (After Effects, Mocha, Sapphire, SAM 2, YOLO, etc.).
Principio rector para todo el plan: no agregar una dependencia nueva hasta agotar lo que se puede resolver con el stack actual (MediaPipe, OpenCV, NumPy, Skia), y no declarar un efecto "listo" sin verificarlo contra los videos reales.
Decisiones de arquitectura ya tomadas
Estas decisiones ya están acordadas en la conversación previa y no deberían volver a debatirse; son el punto de partida para el resto del plan.

1. anchor → track → render. El Effect Script referencia anclas semánticas (right_wrist, left_eye, mouth_center), nunca coordenadas crudas (x: 431, y: 287). Esto permite cambiar el perceptor (MediaPipe → RTMPose → SAM → lo que sea) sin tocar el director artístico ni el renderer.
2. Effect primitives en vez de catálogo cerrado. Los presets actuales (face_neon, fight_comic, paint_reveal, doodle_dance) se reescriben como composición de primitivas (trace, glow, ring, arc, burst, spark, particle, trail, ripple). Un preset existente se redefine como una lista de primitivas; no se elimina nada, se refactoriza por debajo.
3. Capa de restricciones entre director y renderer. El director (LLM o preset) propone efectos, pero no tiene autoridad absoluta: una capa de reglas puede vetar o modificar lo propuesto (eye_state: closed → iris_ring: disabled; tracking_confidence: baja → degradar efecto, no renderizar a ciegas). Esto generaliza el bug puntual del "veto de ojos" a un mecanismo reusable.
4. Fallback jerárquico por confianza, nunca apagado binario. Cuando el detector primario (ej. MediaPipe Face Mesh) cae por debajo de un umbral de confianza, el sistema no debe desaparecer el efecto; debe degradar en cascada: malla facial → keypoints gruesos de cabeza (Pose Landmarker) → óvalo de cabeza vía detector clásico (Haar/DNN de OpenCV) → sostener última posición válida con flujo óptico (cv2.calcOpticalFlowPyrLK) durante una ventana corta.
5. CPU-first como propiedad del producto, no detalle técnico. Que el pipeline corra sin GPU es una ventaja de distribución (llega a más creadores) y de costo. Cualquier herramienta nueva se evalúa primero por si rompe esta propiedad.
6. Invalidación de caché por hash del Effect Script. El manifest.json debe incluir un hash del Effect Script (y de la versión del motor de eventos) usado para generar cada final.mp4, para eliminar la ambigüedad de si un render en disco corresponde a la lógica actual.

Hoja de ruta
No se avanza a la etapa siguiente sin cumplir el gate de la anterior. Esto es intencional: evita repetir la duda que ya tuviste con video_1 (¿el final.mp4 en disco corresponde a la lógica actual?).
Etapa 1 — Consolidar el motor (sin dependencias nuevas)
Todo lo de esta etapa se resuelve con lo que ya está instalado (MediaPipe, OpenCV, NumPy, Skia, Pydantic). Nada aquí requiere YOLO, SAM ni GPU.
Tarea
Qué resuelve
Cómo
Hash del Effect Script en el manifest.json
La duda de si el final.mp4 en disco corresponde a la lógica actual (caso video_1)
Guardar un hash (contenido del Effect Script + versión del motor de eventos) junto al render; si no coincide con el hash actual, forzar re-render
TrackPoint tipado con confianza
Base para el fallback de la Etapa 2
TrackPoint(position, confidence, source, frame) como modelo Pydantic, reemplazando tuplas sueltas de coordenadas
Sistema de anchors formal
Generalizar anchor → track → render
Enumerar anchors de cara (left_eye, right_eye, mouth, chin), cuerpo (left_wrist, right_wrist, left_ankle, right_ankle) y objeto (center, bbox, contour); el renderer nunca sabe de dónde salió el punto
Effect primitives
Reemplazar el catálogo cerrado de presets sin romperlos
Definir primitivas (trace, glow, ring, arc, burst, spark, particle, trail, ripple); reescribir face_neon, fight_comic, paint_reveal, doodle_dance como composición de primitivas por debajo, manteniendo el mismo nombre de preset hacia afuera
Capa de restricciones (constraints)
Generalizar el bug del veto de ojos
Módulo entre Effect Script y renderer que puede vetar o degradar una primitiva según estado (eye_state: closed, tracking_confidence: baja, occluded: true) antes de dibujar
Gate de salida de esta etapa: los tests existentes siguen pasando, y una corrida de face_neon sobre video_2 produce un resultado visualmente idéntico al que ya se verificó bueno (mismo conteo de fotogramas, mismo comportamiento en los anillos de iris).
Etapa 2 — Resolver los problemas ya diagnosticados
Problema
Diagnóstico
Solución propuesta
Cara pintada pierde detección (video_2, calabaza: 6 de 141 fotogramas)
MediaPipe Face Mesh busca textura de piel (pliegues de párpado, borde de labio); la pintura opaca borra esa información, no hay nada que un preprocesado pueda recuperar
Fallback jerárquico: malla facial → si confianza baja, keypoints gruesos de cabeza (Pose Landmarker) → si también falla, óvalo de cabeza vía Image Segmenter de selfie de MediaPipe (sin GPU) → sostener última malla válida con flujo óptico (cv2.calcOpticalFlowPyrLK) durante una ventana corta
Veto de ojos a medias (paint_reveal): algunas luces se dibujan encima de la malla blanca
Problema de orden de composición / falta de exclusión mutua entre capas
Resolver con la capa de restricciones de la Etapa 1: eye_state: closed → iris_ring: disabled, evaluada antes de componer, no después
Duda sobre si video_1 refleja los 8 contactos recalculados
Falta de invalidación de caché
Resuelto por el hash de manifest de la Etapa 1; re-renderizar fight_comic una vez el hash esté en su lugar y confirmar visualmente la carga previa al golpe
Golpes como evento binario (person_contact: true/false)
No se modela la física del golpe, solo el contacto
Descomponer en approach → acceleration → contact → recoil, calculado por derivada numérica (velocidad/aceleración de la muñeca) sobre la pose ya existente, sin modelos nuevos
doodle_dance cortado en el fotograma 168 de 570
Desconocido aún: puede ser timeout, excepción no capturada, o beat sin estrategia asignada
Revisar el log/traceback de esa corrida antes de reintentar; no relanzar a ciegas
Director artista (gpt-5) nunca probado en un video terminado
El validador pasa en tests unitarios, pero no hay evidencia de integración con el renderer procedural
Probar primero en el clip más corto y simple disponible, no en video_1 o video_27, para aislar fallos de integración antes de comprometer una corrida cara
Gate de salida de esta etapa: face_neon, fight_comic, paint_reveal (incluyendo el tramo de la calabaza) y doodle_dance completo corren de punta a punta sin intervención manual, con el veto de ojos funcionando y sin dudas de caché.
Etapa 3 — Benchmark de regresión visual
Usar los propios videos (video_1, video_2, video_27) como suite de pruebas visuales. Cada vez que se toque el motor de eventos, el director o el renderer, correr los presets sobre los tres y marcar la tabla:
Video
Efecto
Tracking
Eventos
Render
Resultado
video_1
fight_comic
✅
⚠️
⚠️
por confirmar carga pre-golpe
video_2 (primer plano)
face_neon
✅
✅
✅
bueno, ya verificado
video_2 (completo, con calabaza)
paint_reveal
⚠️
✅
⚠️
falla tras fotograma 209
video_27
doodle_dance
✅
?
❌
cortado en 168/570
No es necesario automatizar esto con un framework de testing visual desde el inicio; alcanza con repetir la corrida y actualizar la tabla a mano al principio. Automatizarlo (comparación de fotogramas de referencia, por ejemplo con diferencia estructural SSIM) es una mejora posterior, no un requisito para empezar.
Gate de salida de esta etapa: las cuatro filas de la tabla en verde (✅) de forma sostenida, no solo en una corrida puntual.
Etapa 4 — Cuándo sí introducir herramientas externas
Solo después de cumplir el gate de la Etapa 3. La regla es: una herramienta entra porque apareció un cuello de botella concreto, nunca porque existe o suena interesante.
Si aparece este cuello de botella...
...entonces se evalúa
El fallback jerárquico de la Etapa 2 no alcanza (la silueta tampoco se reconoce, hay oclusión severa entre dos personas)
SAM 2, como Segmenter detrás de una interfaz común, no como reemplazo de MediaPipe
Se necesita reconocer objetos que MediaPipe no representa (pincel, botella, gorra, balón)
YOLO11n, como ObjectDetector detrás de una interfaz común
El glow procedural se ve plano frente a lo que ya se logra con composición manual
Recién ahí investigar plugins de glow óptico de terceros, evaluando primero el costo de integrarlos en un pipeline headless sin GUI
Las partículas se ven demasiado simples
Lo mismo: evaluar primero si un sistema de partículas propio en NumPy/Skia alcanza antes de sumar una dependencia de terceros
No entran en esta etapa, ni se evalúan todavía: After Effects, Mocha Pro, Sapphire, Trapcode Particular, Runway, Firefly, Flow Studio, DaVinci Fusion, Topaz Video. No porque sean malas herramientas, sino porque son software de escritorio con licencia, pensado para un compositor humano frente a una línea de tiempo, no para un pipeline headless y barato por video — justo la propiedad que hace viable el proyecto hoy.
Fuera de alcance por ahora
Explícitamente, para que no se filtre por iniciativa propia durante la implementación:
• Cualquier herramienta con licencia de pago o GUI de escritorio (ver Etapa 4).
• Generación de video (Runway, Firefly, Stable Diffusion/ControlNet como refiner): el proyecto es procedural + semántico, no generativo; mezclar ambos paradigmas rompe la reproducibilidad frame a frame.
• Rigging 3D, motion capture, Unreal/Blender como motor de render: el proyecto trabaja en 2D sobre capas RGBA; pasar a 3D es un cambio de arquitectura completo, no una mejora incremental.
• Monetización, pricing, validación de mercado: tema aparte, se retoma una vez haya 3-4 presets estables de punta a punta (ver análisis de costo de API por video y validación con creadores reales, discutido por separado).
Nota para Claude Code
Este documento es la fuente de verdad del orden de trabajo, no una lista de ideas sueltas. Al armar el plan de implementación:

1. Respeta el orden de las etapas y sus gates; no empieces una tarea de la Etapa 2 si el gate de la Etapa 1 no está cumplido.
2. Dentro de la Etapa 1, el orden interno sugerido es: hash de manifest → TrackPoint → anchors → effect primitives → capa de restricciones, porque cada uno es prerrequisito barato del siguiente.
3. Antes de escribir código para cualquier tarea, confirma contra el repositorio real los detalles que aquí se describieron de memoria (nombres exactos de módulos, estructura actual del Effect Script, ubicación del manifest.json), porque este plan se escribió sin acceso al código, solo a partir de la descripción del dueño del proyecto.
4. No agregues ninguna dependencia de la sección "Fuera de alcance" aunque parezca una mejora obvia; si crees que hace falta, señálalo como pregunta abierta en vez de implementarlo.

