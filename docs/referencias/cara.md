# Catálogo cara · efectos glowing del rostro

Unifica los presets `face_neon` y `face_runes`, que ahora son alias de este catálogo. Solo hay luz
sobre la cara real: no se deforma el rostro ni se cambia la piel. Todavía no hay video de referencia;
se calibró con `facil_1` (`api_data/uploads/1f1ba56828/facil_1.mp4`) y se reforzará cuando llegue
un video de referencia de cara con efectos glowing.

## Qué lo dispara

| Evento | Qué detecta | Opciones del catálogo |
| --- | --- | --- |
| `entrance` | Al empezar el video | contorno, escaner |
| `spotlight` | La cabeza es lo que más se mueve | delineado, geometria, malla, cristal, circuito, runas, aro_runas, eco_cabeza, escaner, llamas_ojos, gafas |
| `still` | La persona está quieta | runas, circuito, cristal, delineado |
| `mouth_open` | Boca abierta un rato | carga_boca, aliento, nada |
| `blink` | Parpadeo: los dos ojos se cierran poco tiempo | mascara, nada |
| `wink` | Un solo ojo cerrado (guiño) | destello, nada |
| `eyes_wide` | Ojos muy abiertos | rayos_ojos, llamas_ojos, nada |
| `smile` | Sonrisa, medida contra la mediana de la persona | destellos, mejillas, nada |
| `brows_up` | Cejas arriba, medidas contra la mediana | arcos_cejas, signo, nada |
| `cheeks_puff` | Mejillas infladas | mejillas, nada |
| `pucker` | Labios en beso | beso, nada |
| `head_turn` | Giro rápido de la cabeza (al menos 25°) | eco_cabeza, aro_runas, nada |
| `head_tilt` | Cabeza inclinada hacia un hombro (al menos 15°, sostenida) | aro_runas, geometria, nada |
| `paint_stroke` | Trazo de maquillaje nuevo: figura en detalle, zona de la cara en `kind` | figura_maquillaje, delineado |
| `tool_touch` | La punta del pincel deja pigmento | llama_pincel, nada |
| `face_touch` | Mano en la cara | beso, asombro, nada |
| `surprise` | Cara de impresión: cejas arriba con ojos muy abiertos o boca abierta | impresion_cara, impresion_rayos |
| `gaze_shift` | La mirada salta a otro lado (izquierda, derecha, arriba, abajo) | rafaga_mirada, nada |
| `cover_eyes` | Se tapa los ojos | antifaz, burla, nada |
| `hands_on_head` | Manos en la cabeza | calavera, aro_runas, nada |
| `hand_mouth` | Mano en la boca | cigarro, vapeador, botella, nada |

Las expresiones salen de MediaPipe (0 a 1) y de la orientación de la cabeza. Sin ellas (análisis
viejo o cara perdida) no hay eventos. `gaze_shift` necesita los blendshapes `eyeLook`: un análisis
hecho antes de este cambio no lo tiene hasta que se vuelva a analizar.

## Los dibujos

| Forma | Qué dibuja |
| --- | --- |
| `liner_trace` | Ojos, cejas y labios se delinean en orden, con una chispa en la punta |
| `face_oval_trace` | El contorno de la cara y la línea de la frente se trazan solos |
| `face_geometry` | Triángulos sobre frente, pómulos y mentón que se encienden uno tras otro |
| `face_mesh_live` | La malla de la cara se arma desde la nariz, late y al final se rompe en puntos |
| `face_scan` | Un barrido holográfico baja por la cara y enciende los puntos que toca |
| `face_crystal` | Facetas de cristal (triángulos rellenos y tenues, bordes brillantes) y grietas |
| `face_circuit` | Pistas de circuito que salen de la nariz hacia los bordes, con nodos |
| `face_runes` | Runas que se escriben trazo a trazo en la frente y las mejillas |
| `eye_beams` | Rayos que salen de los ojos hacia afuera |
| `eye_flames` | Llamas de contorno que suben de los ojos |
| `mouth_charge` | Una esfera crece en la boca abierta y al final sale en ondas |
| `breath` | Un aliento de partículas finas que sale de la boca |
| `smile_sparks` | Destellos que saltan de las mejillas al sonreír |
| `brow_lines` | Arcos de sorpresa sobre las cejas |
| `cheek_glow` | Círculos que se inflan en las mejillas |
| `blink_mask` | Al parpadear, por un momento, una máscara de neón (robot o calavera) |
| `rune_orbit` | Un anillo de runas que gira alrededor de la cabeza y se esconde detrás |
| `head_echo` | Copias del contorno de la cabeza que se quedan atrás y se apagan |
| `makeup_figure` | El trazo de maquillaje se vuelve su figura (triángulo, elipse, rectángulo, círculo): se traza, un arco la recorre, se itera hacia afuera y queda como cristal |
| `face_spiders`, `face_ants`, `face_centipede`, `face_roaches` | Bichos de luz que caminan por la cara (largos, ~5 s): entran, cruzan con pausas y salen; las patas siguen lo caminado |
| `face_claws` | Zarpazo de cuatro tajos en mejilla o frente que gotean luz |
| `face_stitches` | Una cicatriz que se traza sola y se cose puntada por puntada |
| `face_cracks` | La piel se raja desde un punto y por las grietas sale luz de brasa |
| `kiss_blow` | Los labios sueltan corazones hacia la cámara y una marca de labios estalla en corazoncitos |
| `shock_face` | Cara de impresión: anillos en los ojos, boca en "O", cejas que saltan y gotas de susto |
| `shock_burst` | Líneas de impacto de cómic alrededor de la cabeza, "!!" y estrellas |
| `gaze_burst` | Al cambiar la mirada, los ojos disparan partículas hacia donde mira |
| `snake_band`, `snake_crown` | Balaca de dos serpientes en la frente, o serpientes que nacen del pelo |
| `red_horns` | Cachos rojos que crecen de la frente y sueltan brasas |
| `death_hook` | Una guadaña enorme entra, se detiene junto al cuello y se retira |
| `skeleton_dance` | Esqueletos pequeños que suben por los lados y bailan |
| `fairies` | Hadas con estela de polvo alrededor de la persona (ver Halloween) |

## Reglas

- El lado de la cara que gira hacia atrás (su ojo se ve mucho más angosto que el otro) no se dibuja.
- Las figuras pequeñas o delgadas reciben menos glow, como en el resto de vfxglow.
- Alrededor del 40% de los cambios de efecto se transforman desde el dibujo anterior en vez de cortar.
- Cada efecto nuevo tiene un color nuevo (`color_per_effect`).
- Sin malla facial, el dibujo cae en plantillas puestas con los ojos y la nariz de la pose.
- Los dibujos sobre la piel llevan poco halo, para no lavar la cara de luz. Los rayos, el aliento y
  los anillos orbitales sí llevan halo completo.
- Los dibujos de línea sobre la cara terminan en polvo de luz (`engine/dissolve.py`), no se apagan.

## Halloween

- Hay 24 rostros de terror en `assets/masks`, sacados de `assets/masks/source/halloween_grid.yaml`
  con las `marks` de cada celda (ojos, nariz, boca).
- El momento de temporada `terror` sortea uno por activación.
- Las hadas (`fairies`) son un efecto `ambient` de la temporada: van y vienen en oleadas y no
  compiten con `one_at_a_time`.

## Pendiente

- Un video de referencia de cara con efectos glowing, para calibrar tiempos (fade, hold, cooldown) y
  formas de cada dibujo.

## Efectos por grados (engine/living_fx.py)

Leen cada fotograma cuánto abre la boca, el volumen, la energía de la cabeza y la mirada.

| Forma | Qué hace | Se activa con |
| --- | --- | --- |
| `dragon_breath` | Llamarada cuyo largo sigue a la boca o al soplido; apunta hacia donde gira la cabeza | `mouth_open`, `cheeks_puff` |
| `sonic_pulse` | Ondas que salen de la boca con el tamaño del volumen y barras de ecualizador | `speaking` |
| `puppet_strings` | Hilos desde una cruceta a sienes, hombros y muñecas; vibran con el movimiento y se rompen | `head_tilt`, `head_turn`, pausas |
| `raven` | Cuervo que orbita, se posa en el hombro si la persona se queda quieta y acaba en plumas | `head_turn`, pausas |
| `eye_curse` | Sellos que siguen la mirada, se apagan al cerrar los ojos y sueltan una onda al abrirlos | `blink` |

`speaking` exige volumen y boca en movimiento a la vez: con solo música de fondo no se dispara. Los
análisis anteriores no tienen volumen hasta reanalizar el video.
