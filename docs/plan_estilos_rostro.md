# Estilos para el rostro: estado y plan (para retomar en una sesión nueva)

Nota escrita el 2026-10-30 para no tener que reconstruir el contexto. Leer esto primero y luego solo
los archivos que la tarea pida.

## Contexto en una línea

vfxglow (Vexora) dibuja efectos glowing sobre videos. Además de baile y peleas, ahora hay una línea
de **efectos para el rostro**: el catálogo `cara` y un **modo Halloween** con rostros de terror en
neón sacados de una cuadrícula de 24 personajes, ya todos hechos. Además hay bichos que caminan por
la cara, heridas de luz, besos lanzados, caras de impresión, ráfagas con la mirada, balacas de
serpientes, cachos, guadaña, esqueletos y hadas.

## Reglas que dio el usuario (no romperlas)

- Solo efectos glowing: luz sobre la persona real; nada de deformar la cara, filtros de belleza ni
  caricaturas de cuerpo entero.
- En `cara`, **un solo efecto a la vez** (`one_at_a_time: true` en el catálogo).
- Preferir **partículas que salen del rostro o lo rodean** (pesan más en el catálogo que los dibujos
  de líneas).
- Con un **rostro especial** puesto (máscara de terror) no va nada más sobre la cara: la coreografía
  rechaza esas opciones y el motor apaga las que ya estaban (`engine/face_zone.py`).
- Las máscaras se arman rápido (~0,8 s), la luz corre por sus líneas "como agua por una zanja" (no
  giran las figuras) y al irse se sueltan en polvo fino con figuritas diminutas, con mucha expansión
  y fluido (~1,1 s, `engine/dissolve.py`). Por eso duran ~2,4 s y no 1,5.
- Bichos que caminan: efectos largos (~5 s), como los filtros de Instagram. Heridas: solo luz.
- En `baile` los efectos de cara son cortos; en `cara` pueden durar más.
- ~40% de los cambios de efecto se transforman del dibujo anterior al nuevo (continuidad), pero solo
  si el anterior ya terminó.
- Lo delgado o pequeño, con poco halo. Tareas mecánicas a subagentes con modelo barato.

## Qué existe

| Pieza | Dónde |
| --- | --- |
| Expresiones y orientación de la cabeza (MediaPipe blendshapes) → eventos `mouth_open`, `blink`, `wink`, `eyes_wide`, `smile`, `brows_up`, `cheeks_puff`, `pucker`, `head_turn`, `head_tilt` | `analysis/expressions.py`, `analysis/mediapipe_backend.py` |
| Trazo de maquillaje → evento `paint_stroke` (figura + zona) | `analysis/appearance.py` |
| ~23 dibujos de cara (delineado, malla, cristal, runas, ojos, boca, partículas `face_emanate`, `face_swirl`, `face_sparkle_rain`, `eye_sparks`) | `engine/face_glow.py` |
| Catálogo `cara` (alias de los viejos presets `face_neon` y `face_runes`) | `configs/catalogs/cara.yaml`, doc `docs/referencias/cara.md` |
| Cuadrícula de 24 rostros neón (fuente) y su índice (n, id, nombre) | `assets/masks/source/halloween_grid.png` y `.yaml` |
| Herramienta: celda de la cuadrícula → trazos vectoriales con rol, en coordenadas de cara. Los rasgos salen de `marks` en el índice (leídos a mano); el detector de huecos solo sirve para Ghostface | `tools/mask_from_grid.py --cell N` → `assets/masks/<id>.yaml` |
| Bichos: arañas, hormigas, ciempiés, cucarachas | `engine/face_creatures.py` |
| Heridas: zarpazo, cicatriz cosida, grietas | `engine/face_wounds.py` |
| Beso lanzado, impresión (ojos y líneas de impacto), ráfaga de la mirada | `engine/face_moods.py` |
| Balaca y corona de serpientes, cachos rojos, gancho de la muerte, esqueletos, hadas | `engine/head_beasts.py` |
| Desintegración en polvo (máscaras y dibujos de cara) | `engine/dissolve.py` |
| Eventos `surprise`, `speaking` y `gaze_shift` (la mirada usa las expresiones `eyeLook*`) | `analysis/expressions.py` |
| Volumen por fotograma (`FrameRecord.voice`) | `analysis/voice.py` |
| Efectos que responden por grados: aliento de dragón, pulso sónico, marioneta, cuervo, sellos en los ojos | `engine/living_fx.py` |
| Señales por grados en el motor: `runtime.voice`, `runtime.head_pose`, `runtime.energy` (además de `runtime.expressions`) | `engine/bodyglow.py` |
| Máscara viva `terror_<id>` (se ajusta por los ojos, grita con `jawOpen`, parpadea, luz que fluye, salida en figuras de Halloween) | `engine/horror_masks.py` |
| Halloween: la máscara como momento de temporada | `configs/seasons.yaml` (halloween → moments), `director/seasons.py` |
| Opciones de motor nuevas: `keep_on_cut` (sigue tras un corte de toma), `one_at_a_time` y `moment_scale` en el catálogo | `director/schema.py`, `director/choreography.py`, `engine/engine.py` |

Video de prueba: `api_data/uploads/3c00dd033c/facil_1.mp4` (la API que corre el usuario mueve las
subidas; si no está, buscar `facil_1.mp4` en `api_data/uploads/`). Resultado:
`runs/facil_1-34ec1af4/output/cara__halloween.mp4`.

    vfxglow run --video api_data/uploads/3c00dd033c/facil_1.mp4 --catalog cara --season halloween

## Siguiente paso (plan)

1. Que el usuario vea el render y diga qué ajustar.
2. Cuando llegue un video de referencia de cara con efectos glowing: analizarlo como los de baile
   (`docs/criterio_de_analisis.md`) y calibrar tiempos y formas.
3. Falta probar en video real lo que `facil_1` no tiene: boca abierta y cara de impresión.

Para revisar efectos sin renderizar todo, dibujarlos sobre fotogramas reales con `EffectEngine` y un
evento sintético (como `tools/preview.py`); los tramos de frente de `facil_1` empiezan en los
fotogramas 2 y 470.

## Pendientes conocidos

- Sin video de referencia de cara: tiempos y pesos calibrados a ojo sobre `facil_1`.
- `facil_1` no tiene boca abierta ni ojos muy abiertos: la carga en la boca, el grito y `surprise` no
  se probaron con un evento real (sí con eventos sintéticos en vistas previas).
  El aliento de dragón tampoco: se probó con una apertura de boca simulada. Hace falta un video donde
  la persona abra la boca, grite o sople para calibrarlo. El fuego se ve mejor sobre fondos oscuros.
- Los análisis anteriores a octubre de 2026 no tienen malla facial (se borraba en `analysis/cast.py`)
  ni mirada: hay que reanalizar el video. Al cambiar el código de análisis eso ocurre solo.
- El gancho de la muerte entra desde un lado de la cabeza; no lo agarra la mano.
- Si la cara gira mucho, el lado de atrás se oculta por el ancho de los ojos; no hay oclusión 3D.
- Commits en `main` sin subir al cerrar esta sesión: subirlos cuando el usuario lo pida.
