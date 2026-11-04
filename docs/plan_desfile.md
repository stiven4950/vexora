# Catálogo desfile: estado y contexto (para retomar en una sesión nueva)

Nota escrita el 2026-11-03; lucecitas, anillos y pisadas añadidos el 2026-11-04. Leer esto primero; el detalle de cada referencia está en
`docs/referencias/video_46.md` y `docs/referencias/video_55.md`.

## Qué es

Estilo para videos de moda o modelaje con cambios de outfit: la persona camina o posa casi quieta, sin
gestos bruscos. No se dibuja lo que hace: **se delinea y se ilumina la ropa**. Cada outfit es un
capítulo con su color, sus trazos (dependen de la prenda), sus zonas pintadas y una pieza de luz en la
cabeza.

Referencias (originales en `glowing/data/original/`, glowing en `glowing/data/glowing/`):
- **video_46**: desfile en la calle, 5 outfits separados por cortes deslizantes de 2-3 cuadros. Trazos
  de la prenda, calzado y bolso delineados, pieza de cabeza por outfit.
- **video_55**: prueba de outfits frente al espejo, sumando capas. Zonas pintadas con destellos (su
  recurso principal), revelado del outfit nuevo, estilo holográfico, onda en el pantalón, burbujas,
  logo, estela de la mochila y cierre de prisma. El usuario lo dio por "excelente".

Probar: `vfxglow run --video ../glowing/data/original/video_55.mp4 --catalog desfile` (y video_46).
Salida en `runs/video_55-fcd40e65/output/desfile.mp4` y `runs/video_46-e91b1774/output/desfile.mp4`.

## Decisiones del usuario

- Precisión de contornos: camino rápido (segmentador más bordes de la imagen, ajustados al borde real).
  **Mejora futura anotada**: SAM 2 por prenda (~0,9 s por cuadro), quizá como opción "alta calidad".
- Los trazos dependen del outfit. Varias técnicas sirven también en baile y en cara neón.
- Dibujos profesionales, nunca infantiles (memoria `dibujos-profesionales`).

## Piezas

| Pieza | Dónde | Qué hace |
| --- | --- | --- |
| Trazos de la prenda | `analysis/garment.py` (`frame_strokes`, `Tracker`, `ensure_garment`) | Por cuadro, con el segmentador multiclase de MediaPipe: fronteras prenda/piel y prenda/calzado, contorno de "otros" (calzado, bolso; nada arriba de la persona), bordes internos con Canny (tramos de una costura unidos con `join_chains`) y el logo (`_logo`). Ajuste al borde real (`snap`), ids estables por toma (distancia media de puntos). Solo si el guion lo pide; queda en `analysis/garment.jsonl` |
| Zonas de la prenda | `analysis/garment.py` (`frame_zones`) | La ropa partida con la pose: torso, mangas, piernas, bolso, calzado de cada pie; descarta lo que no toca a la persona (reflejos del espejo). En el mismo jsonl (`zones`) |
| Cambios de outfit | `analysis/garment.py` (`outfit_changes`, `outfit_peaks`) | Picos del cambio de color de la ropa (Bhattacharyya ≥ 0,33, ventanas de 8 cuadros, 0,8 s entre cambios, se corre a un corte a ≤4 cuadros). video_46 → 27, 59, 90, 122; video_55 → 57. Se calcula al dirigir si el catálogo tiene `outfits` (`Pipeline._with_outfits`), se guarda en `analysis/outfits.json` y va en `MotionBrief.outfits` |
| Cortes deslizantes | `analysis/beats.py` (`_structure_cuts`, `_scene_cuts`) | Transiciones de 2-3 cuadros (`SLIDE_RATIO`, `SLIDE_MERGE`); cortes vecinos de los dos detectores se funden |
| Eventos por outfit | `director/choreography.py` (`outfit_events`) | Con `outfits: true`, un evento por cada acción `outfit*` del catálogo y cada outfit. Las capas `outfit*` no compiten por el tope de dos focos |
| Color por outfit | `choreography.py` (`cut_chapters`, `build_chapters(distinct=True)`) | Un color por outfit, sin repetir hasta agotar la paleta |
| Reinicio entre activaciones | `engine/engine.py` | Un efecto que pasa sin pausa a otra activación vuelve a empezar (fase y color de capítulo); `runtime.take_start` para elegir trazos por toma |
| Orejas de gato sueltas | `engine/face_symbols.py` (`cat_ears`) | Las de la mirada felina, como pieza de cabeza |

## Efectos (`engine/garment_fx.py`)

| Forma | Acción del catálogo | Qué dibuja |
| --- | --- | --- |
| `garment_lines` | `outfit` | Por toma, los trazos que más aparecen con más contraste (calzado y bolso, fronteras, costuras, logo); sigue la tela, sale en guiones los últimos 6 cuadros; dos destellos recorren las líneas largas; en ~35% de los outfits, holográfico (copias roja y azul corridas, calzado en arcoíris; fijo con `style.variants.holo`) |
| `garment_reveal` | `outfit_reveal` | Outfit nuevo: barrido diagonal de luz (0,3 s), ropa entera teñida con su silueta (0,4 s), fundido (0,35 s). No en el primer outfit; opción `nada` 0,4 |
| `garment_zones` | `outfit_zone` | Una zona por turno (~0,9 s): tinte suave sin borde y un brillo diagonal con destellos en el borde; el turno sigue entre cortes |
| `garment_ecg` | `outfit_wave` | Onda de electrocardiograma que cruza el pantalón a la altura de la cadera (~45%). Se llamaba `garment_wave`, que ya existía en `ambient_fx` (cara) |
| `garment_bubbles` | `outfit_bubbles` | Anillos con separación de color que suben a los costados; uno en la muñeca más rápida (~35%) |
| `garment_trail` | `outfit_trail` | Estela del bolso o la mochila cuando se mueve rápido |
| `garment_prism` | `outfit_prism` | Cierre: en el último segundo, destellos finos de arcoíris en diagonal sobre la ropa. `desfile` no usa `closing_stars` (atenuaba todo) |

## Piezas con la pose (`engine/runway_fx.py`)

No necesitan los trazos de la prenda (sirven también en baile); `hair_lights` y `joint_rings` piden la
segmentación (`analysis/regions.py`, `NEEDS_REGIONS`).

| Forma | Acción del catálogo | Qué dibuja |
| --- | --- | --- |
| `hair_lights` | `outfit_head` (opción `lucecitas`) | Doce lucecitas en cruz repartidas por el pelo de verdad alrededor de la cabeza (se eligen una vez de la máscara de pelo y quedan pegadas a la cara); titilan. Sin pelo a la vista, una plantilla sobre la coronilla. Outfit naranja de video_46 |
| `joint_rings` | `outfit_joints` (`anillos` 0,35, `nada` 0,65) | Anillo en perspectiva en cada codo y rodilla (mitad de atrás tenue, un brillo que da la vuelta), paréntesis por fuera de cada hombro y una línea por el costado de la pierna de adelante. Si la articulación no cae sobre la persona (el codo que la pose inventa detrás del cuerpo), no va; con las rodillas juntas queda solo la de adelante. Outfit cian de video_46 |
| `step_glint` | `step` (`pisada` 0,7, `cooldown: 6`) | Cuando el pie se apoya (`anchor: end`, así toma el color del outfit de ese momento), la suela se enciende y un anillo plano se abre en el piso, bajo el zapato (la última fila de la persona bajo el pie), con chispas a ras del piso; ~1/3 s. `stomp` y `foot_strike` siguen siendo del baile |

Pieza de cabeza (`outfit_head`): con gorra → visera (barra sobre los ojos), con sombrero o boina → aro,
con gafas → gafas (peso 20, filtro `accessories`); si no, cachos, orejas, corona, aro o lucecitas con
`max_uses: 1`.

Catálogo: `configs/catalogs/desfile.yaml` (`needs: [garment]`, `outfits: true`, `cut_chapters: true`,
`keep_on_cut: true`, `cooldown: 0` en los disparadores).

Pruebas: `tests/test_garment.py` (trazos, seguimiento, uniones, logo, zonas, cambios de outfit, cortes
deslizantes, cada efecto) y `tests/test_runway.py` (lucecitas sobre el pelo, anillos solo sobre la persona
y la rodilla de adelante, anillo de la pisada en el piso). Las formas `garment_*` se saltan en `tests/test_dance.py` porque necesitan
el análisis de la prenda.

## Pendiente

- Prendas oscuras sobre fondo oscuro (el abrigo negro de video_46): Canny no ve sus bordes delanteros.
- El patrón de la prenda (puntos en el acolchado) no se dibuja; el logo de video_55 casi no sale.
- SAM 2 por prenda (mejora de precisión anotada).
