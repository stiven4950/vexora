# Estilos para el rostro: estado y plan (para retomar en una sesión nueva)

Nota escrita el 2026-10-30 para no tener que reconstruir el contexto. Leer esto primero y luego solo
los archivos que la tarea pida.

## Contexto en una línea

vfxglow (Vexora) dibuja efectos glowing sobre videos. Además de baile y peleas, ahora hay una línea
de **efectos para el rostro**: el catálogo `cara` y un **modo Halloween** con rostros de terror en
neón sacados de una cuadrícula de 24 personajes. Por ahora solo el personaje 01 (Ghostface) está
hecho; la idea es probar que funciona y luego sacar los demás.

## Reglas que dio el usuario (no romperlas)

- Solo efectos glowing: luz sobre la persona real; nada de deformar la cara, filtros de belleza ni
  caricaturas de cuerpo entero.
- En `cara`, **un solo efecto a la vez** (`one_at_a_time: true` en el catálogo).
- Preferir **partículas que salen del rostro o lo rodean** (pesan más en el catálogo que los dibujos
  de líneas).
- Con un **rostro especial** puesto (máscara de terror) no va nada más sobre la cara: la coreografía
  rechaza esas opciones y el motor apaga las que ya estaban (`engine/face_zone.py`).
- Las máscaras duran como un efecto normal (~1,5 s): se arman rápido, la luz corre por sus líneas
  "como agua por una zanja" (no giran las figuras) y al irse se deshacen en murciélagos, calabazas,
  fantasmas y estrellas de colores.
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
| Herramienta: celda de la cuadrícula → trazos vectoriales con rol (ojos, nariz, boca, línea) en coordenadas de cara | `tools/mask_from_grid.py --cell N` → `assets/masks/<id>.yaml` |
| Máscara viva `terror_<id>` (se ajusta por los ojos, grita con `jawOpen`, parpadea, luz que fluye, salida en figuras de Halloween) | `engine/horror_masks.py` |
| Halloween: la máscara como momento de temporada | `configs/seasons.yaml` (halloween → moments), `director/seasons.py` |
| Opciones de motor nuevas: `keep_on_cut` (sigue tras un corte de toma), `one_at_a_time` y `moment_scale` en el catálogo | `director/schema.py`, `director/choreography.py`, `engine/engine.py` |

Video de prueba: `api_data/uploads/3c00dd033c/facil_1.mp4` (la API que corre el usuario mueve las
subidas; si no está, buscar `facil_1.mp4` en `api_data/uploads/`). Resultado:
`runs/facil_1-34ec1af4/output/cara__halloween.mp4`.

    vfxglow run --video api_data/uploads/3c00dd033c/facil_1.mp4 --catalog cara --season halloween

## Siguiente paso (plan)

1. Que el usuario vea el último render y apruebe Ghostface.
2. Sacar los otros 23 personajes: `tools/mask_from_grid.py --cell N` para N = 2..24, revisar la hoja
   de roles de cada uno (pintar los trazos por rol) y ajustar la clasificación donde falle. Los de
   rasgos poco marcados (pelo, sombrero, capucha, la calabaza 23, Predator 18, Alien 17) seguramente
   necesiten reglas propias (p. ej. la calabaza no tiene cara humana: ojos y boca son huecos grandes).
3. Agregarlos a Halloween (`seasons.yaml`) y a `cara` (opción `mascara_terror` con varias formas;
   se sortea una por activación).
4. Cuando llegue un video de referencia de cara con efectos glowing: analizarlo como los de baile
   (`docs/criterio_de_analisis.md`) y calibrar tiempos y formas.

## Pendientes conocidos

- Sin video de referencia de cara: tiempos y pesos calibrados a ojo sobre `facil_1`.
- `facil_1` no tiene boca abierta: la carga en la boca y el grito no se probaron en video real (sí en
  vistas previas).
- Si la cara gira mucho, el lado de atrás se oculta por el ancho de los ojos; no hay oclusión 3D.
- Commits en `main` sin subir al cerrar esta sesión: subirlos cuando el usuario lo pida.
