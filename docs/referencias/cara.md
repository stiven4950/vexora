# Catálogo cara · efectos glowing del rostro

Unifica los presets `face_neon` y `face_runes`, que ahora son alias de este catálogo. Solo hay luz
sobre la cara real: no se deforma el rostro ni se cambia la piel. Todavía no hay video de referencia;
se calibró con `facil_1` (`api_data/uploads/1f1ba56828/facil_1.mp4`) y se reforzará cuando llegue
un video de referencia de cara con efectos glowing.

## Qué lo dispara

| Evento | Qué detecta | Opciones del catálogo |
| --- | --- | --- |
| `entrance` | Al empezar el video | contorno, escaner |
| `look` | Lugar reservado cada ~8 s para un efecto largo | ojos_cleopatra, fantasma, ojos_hielo, mini_yo |
| `ambient` | Cada ~3 s, irregular, además del efecto de la cara | portal_cabeza, agujeros_negros, cabello_energia, aro_cabeza, onda_prenda |
| `spotlight` | La cabeza es lo que más se mueve | mini_yo, fantasma, ojos_hielo, ojos_cleopatra, delineado, geometria, malla, cristal, circuito, runas, aro_runas, eco_cabeza, escaner, llamas_ojos, gafas |
| `still` | La persona está quieta | mini_yo, fantasma, ojos_hielo, ojos_cleopatra, runas, circuito, cristal, delineado |
| `mouth_open` | Boca abierta un rato | carga_boca, aliento, nada |
| `blink` | Parpadeo: los dos ojos se cierran poco tiempo | ojos_hielo, mascara, nada |
| `wink` | Un solo ojo cerrado (guiño) | destello, nada |
| `eyes_wide` | Ojos muy abiertos | ojos_hielo, ojos_cleopatra, ojos_laser, rayos_ojos, llamas_ojos, nada |
| `smile` | Sonrisa, medida contra la mediana de la persona | emocion, destellos, mejillas, nada |
| `frown` | Ceño fruncido u ojos entrecerrados, sin sonreír | ojos_laser, emocion, nada |
| `brows_up` | Cejas arriba, medidas contra la mediana | emocion, arcos_cejas, signo, nada |
| `cheeks_puff` | Mejillas infladas | mejillas, nada |
| `pucker` | Labios en beso | emocion, beso, nada |
| `head_turn` | Giro rápido de la cabeza (al menos 25°) | fantasma, eco_cabeza, aro_runas, nada |
| `head_tilt` | Cabeza inclinada hacia un hombro (al menos 15°, sostenida) | aro_runas, geometria, nada |
| `paint_stroke` | Trazo de maquillaje nuevo: figura en detalle, zona de la cara en `kind` | ojos_cleopatra, figura_maquillaje, delineado |
| `tool_touch` | La punta del pincel deja pigmento | llama_pincel, nada |
| `face_touch` | Mano en la cara | beso, asombro, nada |
| `surprise` | Cara de impresión: cejas arriba con ojos muy abiertos o boca abierta | emocion, impresion_cara, impresion_rayos |
| `gaze_shift` | La mirada salta a otro lado (izquierda, derecha, arriba, abajo) | ojos_laser, rafaga_mirada, nada |
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
- Alrededor del 40% de los cambios de efecto se transforman desde el dibujo anterior en vez de cortar:
  cada línea viaja a la más cercana del dibujo nuevo y cambia de color en ~0,35 s, con chispas; solo
  entre dibujos de la misma zona (cabeza o cuerpo).
- Cada efecto nuevo tiene un color nuevo (`color_per_effect`).
- Sin malla facial, el dibujo cae en plantillas puestas con los ojos y la nariz de la pose.
- Los dibujos sobre la piel llevan poco halo, para no lavar la cara de luz. Los rayos, el aliento y
  los anillos orbitales sí llevan halo completo.
- Los dibujos de línea sobre la cara terminan en polvo de luz (`engine/dissolve.py`), no se apagan.
- Un solo efecto principal sobre la cara. Con él puede ir uno periférico, que va alrededor sin cruzar
  los rasgos (`face_emanate`, `head_echo`, `emotion_burst`, `shock_burst`, `skeleton_dance`, `raven`,
  `fairies`); el remolino, el anillo de runas y la lluvia de destellos pasan por delante de la cara y
  son principales. Con uno que cubre toda la cara (máscaras, `blink_mask`, `face_mesh_live`,
  `face_crystal`, disfraces de cara) no va nada (`engine/face_zone.py`).

## Familia de ojos (engine/eye_family.py)

Seis variantes que comparten el seguimiento del iris y del párpado, cuatro fases (entrada, activo,
reacción, salida en polvo) y las señales de `engine/face_signals.py`. Cada aparición sortea una variante
de la opción y sus perillas (intensidad, velocidad, densidad, estela, trazo, movimiento, paleta propia
o del capítulo) con una semilla de la forma, la persona y el momento; `style.variants` las limita.

| Forma | Qué dibuja | Cómo reacciona |
| --- | --- | --- |
| `eyes_fire` | Anillo ámbar en el iris y llamas finas que suben del párpado | Se encoge al cerrar los ojos, se aviva con la mirada fija, deja estela al girar, baja con la cara relajada |
| `eyes_galaxy` | Iris de noche con estrellas que giran y una constelación en la sien | Las estrellas se corren hacia donde mira; el ojo que guiña suelta estrellas |
| `eyes_storm` | Iris blanco y cian con arcos eléctricos hacia la sien | Más brillo y arcos más largos con el ceño; chispas al abrir los ojos |
| `eyes_void` | Anillo violeta de borde brillante y volutas que se enroscan hacia el ojo | Crece con los ojos muy abiertos y se repliega al cerrarlos |
| `eyes_feline` | Contorno del ojo, pupila vertical, bigotes de luz y orejas de gato sobre la cabeza (contorno curvo, oreja interior, mechones, pincel en la punta) | La pupila se angosta con los ojos abiertos y sigue la mirada; las orejas se paran con los ojos muy abiertos, se echan atrás con el ceño, se sacuden al parpadear y se mecen al girar |
| `eyes_scanner` | Retícula sobre el iris, barrido y líneas de datos en la sien | Un barrido nuevo en cada salto de la mirada; se enciende con la mirada fija |

Opciones: `ojos_familia` (`look`, `spotlight`), `ojos_mirada` (`still`), `ojos_vacio` (`eyes_wide`),
`ojos_tormenta` (`frown`), `ojos_escaner` (`gaze_shift`) y `ojos_galaxia` (`wink`). Solo el iris y el
párpado se devuelven al motor, en orden fijo, para que la continuidad transforme ojo en ojo; lo de
alrededor es línea fina.

## Símbolos, maquillaje de luz y criaturas (entrega 2)

Con la misma base que la familia de ojos (fases, perillas, señales). El maquillaje sale de
referencias de maquillaje real que dio el usuario el 2026-11-02 (alas UV, emblema egipcio, líneas
neón, Medusa y rostro que se desintegra): línea fina y nítida, rellenos tenues y puntos.

| Forma | Qué dibuja | Cómo reacciona | Cobertura |
| --- | --- | --- | --- |
| `third_eye` | Ojo vertical en la frente: doble almendra, iris de rayos grabados, pupila y bindi | Se abre con las cejas (contra lo habitual de esa cara), parpadea con los ojos, suelta rayos si las cejas suben de golpe | baja |
| `rune_shift` | Runas en la frente y las mejillas | Sus trazos viajan hasta otra runa al parpadear, al girar la cabeza o cada tanto | media |
| `light_crown` | Diadema de joyería en perspectiva: banda con perlas, puntas ojivales, gota y estrella | Las puntas crecen con la sonrisa y las cejas; un brillo la recorre | periférica |
| `butterfly_wings` | Alas de mariposa UV alrededor de cada ojo: celdas amarillas y cian, contorno azul, puntos blancos | Aletean al parpadear, se abren con los ojos muy abiertos, los puntos brillan con la sonrisa | media |
| `pharaoh_mark` | Emblema alado egipcio (plumas en tres hileras, escarabajo con ankh, disco solar), fila de puntos y ojo de Horus | Se traza al entrar | media |
| `neon_veins` | Líneas neón por la anatomía: puntos al centro, sienes, ganchos sobre las cejas, lágrimas con gota, labios, barbilla y pecas | Un pulso las recorre, más rápido al sonreír o al hablar; bajan con la cara relajada | media |
| `porcelain_cracks` | Porcelana fracturada al estilo kintsugi: grietas de oro y luz blanca por un lado del rostro, sin cruzar ojos ni boca | Crecen con el ceño, los ojos muy abiertos o la boca abierta; sueltan esquirlas si el gesto sube de golpe; se cierran al relajarse | media |
| `face_dissolve` | El contorno se vuelve polvo azul y del costado de la cabeza sale humo rosa y naranja; chispas al frente | El viento sopla más fuerte al girar o moverse la cabeza; al irse, se lo lleva todo | media |
| `eye_butterflies` | Mariposas de seis especies (monarca, golondrina, paisley, festoneada, polilla, ocelo; de referencias de ilustración del usuario) que salen de los párpados y vuelan en vaivén sobre la cabeza; por detrás de la cabeza se ocultan | Cada parpadeo suelta una; la órbita se corre hacia donde mira | periférica |
| `holo_snake` | Serpiente holográfica de línea fina que se desliza por fuera del contorno de la cara | Más rápida al girar; se acerca a la boca abierta sin entrar; sin malla se repliega | periférica |
| `medusa_snakes` | Serpientes de neón que nacen del pelo, se mecen en S y enroscan la punta; con volumen: cuerpo en franjas de azul (sombra) a rosa casi blanco (luz), brillo húmedo con destellos por el lomo, borde iluminado y escamas curvas sobre el cilindro | Se yerguen con la boca abierta y se mecen más rápido al girar | periférica |

- Con un efecto grande en la cara (máscaras completas, maquillaje de luz, Medusa), la capa de ambiente
  se aparta de a poco y vuelve cuando se va (`face_zone.is_big`, `engine.py`).
- Llamas de ojos, rayos, chispas, láser, Cleopatra, hielo, aliento, ondas y sellos sortean intensidad y
  grosor por aparición (`bodyglow.VARIED`), como las familias.

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
