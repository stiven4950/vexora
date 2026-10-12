# Catálogo de acciones y reacciones

El efecto no se decide por video sino por **acción**. El análisis detecta acciones (un golpe
rápido, un contacto, dos cuerpos que chocan); el catálogo dice qué reacciones visuales puede
provocar cada una y con qué peso; el coreógrafo sortea una reacción por ocurrencia.

```text
análisis ──> eventos (acciones) ──> coreógrafo + catálogo ──> Effect Script ──> motor
                                         │
                                         └─> scripts/choreography.json (qué salió y por qué)
```

- **Determinista:** la misma semilla da la misma coreografía. Otra semilla, otra coreografía.
- **"Puede aparecer o no":** cada acción incluye la opción `nada` con su peso.
- **Trazable:** `runs/<video>/scripts/choreography.json` lista cada acción con su segundo, quién
  la hizo y la reacción elegida.
- **Extensible sin código:** los catálogos son YAML en `configs/catalogs/`. Un efecto nuevo sí
  requiere código en el motor; combinarlo y repartir su frecuencia no.

## Uso

```bash
vfxglow run --video ../glowing/data/original/video_1.mp4 --catalog pelea            # semilla del catálogo
vfxglow run --video ../glowing/data/original/video_1.mp4 --catalog pelea --seed 7   # otra coreografía
```

Salida: `runs/<video>/output/pelea.mp4`, guion en `scripts/pelea.json` y decisiones en
`scripts/choreography.json`. Vista previa de fotogramas sueltos de esa coreografía:

```bash
python tools/preview.py --run runs/video_1-34f2d20d --video ../glowing/data/original/video_1.mp4 \
  --script runs/video_1-34f2d20d/scripts/pelea.json --frames 46,352,528 --tile 400
```

## Formato del catálogo

```yaml
name: pelea
seed: 21
colors: [[1.0, 0.55, 0.12], [0.18, 0.5, 1.0]]   # color por persona (person_0, person_1)
defaults: {...}          # plantilla común; cada efecto solo escribe lo que cambia
always: [...]            # efectos sin sorteo (con su propia probabilidad, p. ej. partículas)
reactions:
  - action: fast_swing   # nombre del evento del análisis
    cooldown: 0          # fotogramas mínimos entre dos reacciones a esta acción
    options:
      - name: swoosh
        weight: 0.5
        cooldown: 0              # fotogramas mínimos entre dos usos de ESTA opción
        requires_person: false   # la acción debe venir de person_N (quién y hacia quién)
        limbs: []                # solo para estas extremidades (p. ej. [left_wrist, right_wrist])
        effects:
          - type: swoosh
            target: {kind: joint, id: "left_wrist,right_wrist"}
            style: {...}
            trigger: {hold: 8, fade_in: 1, fade_out: 4}
      - name: nada
        weight: 0.25
```

Cada efecto de una opción recibe un trigger con `event: <acción>` y `frames: [...]`, los
fotogramas en que salió elegida. Con un evento que nombra una extremidad, el swoosh y el brazo
musculoso solo dibujan esa extremidad.

## Acciones que detecta el análisis

| Acción | Qué es |
| --- | --- |
| `fast_swing` | Una extremidad supera la velocidad umbral varios fotogramas |
| `person_contact` | La muñeca de una persona alcanza el torso o la cabeza de la otra |
| `strike_windup` / `strike_recoil` | 8 fotogramas antes de un contacto / retroceso de la muñeca después |
| `fist_clash` | Manos de dos personas que se acercan deprisa y se tocan |
| `body_bump` | Dos cuerpos que chocan (cajas solapadas; el tracker suele fusionarlos) |
| `lull` | Pausa tras un tramo de acción: todos casi quietos (fin de una ronda). Mediana de la actividad, ignora picos sueltos |
| `intent` | En la pausa, una mano que se pone en marcha (por desplazamiento, no velocidad: llevar la mano al pecho es lento). `kind`: `hand_to_chest`, `guard_up`, `arm_back`, `stir` |
| `intended_strike` | Golpe rápido que llega poco después de una intención de la misma persona |
| `foot_strike`, `jump`, `turn`, `still`, `raise_hand`, `arms_crossed`, `hand_open/closed` | Ver `analysis/events.py` |

## Filtros de una opción

| Campo | Efecto |
| --- | --- |
| `limbs` | Solo si la acción es de estas extremidades |
| `kinds` | Solo para estos subtipos de la acción (`MotionEvent.kind`, p. ej. `hand_to_chest`) |
| `accessories` | Solo si la persona lleva uno de estos accesorios; en acciones de escena (una pausa) se dibuja en todos los que lo lleven |
| `requires_person` | La acción debe venir de una persona identificada |
| `cooldown` | Fotogramas mínimos entre dos usos de la opción |

## Accesorios

Qué lleva cada persona (`sunglasses`, `glasses`, `mask`, `hat`, `cap`, `headband`, `hood`,
`earrings`) se clasifica una vez por persona con el VLM de `analysis.scene`: una hoja con 6
recortes de su cabeza repartidos en el video, una llamada. Queda en `motion_brief.json` →
`accessories` con el tramo de cada uno. La posición en cada fotograma sale de los ojos de la
pose, escalada con los hombros. Sin clave de API, o para forzarlo:

```yaml
analysis:
  accessories:
    manual: {person_1: [sunglasses]}
```

Un umbral de píxeles no sirve aquí: a 720 px los ojos miden ~17 px y el tono de piel confunde.

## Colores y chispas diminutas

- `style.palette`: lista de colores; cada activación (un golpe, un swoosh, unas gafas) sortea dos
  de ella con semilla. En `pelea.yaml` está en `defaults` con 10 neones, así que la heredan todos
  los efectos. Sin `palette`, se usa `colors` (un color fijo por persona).
- `style.micro_sparks`: en `flame_burst`, `clash` y `stars`, cantidad de chispas muy finas que
  salen disparadas del golpe al empezar el impacto y caen (un tercio casi blancas).

## Figuras disponibles

| Efecto | Figuras (`style.shapes`, una por activación al azar) |
| --- | --- |
| `eyewear` | `frames`, `stars`, `hearts`, `mask` (antifaz), `visor`, `rings`, `glint` |
| `intent_mark` | `rune`, `rays`, `halo`, `spiral`, `sparkle`, `cross` |
| `blade_glow` | `neon`, `lightning` (rayo), `fire` (fuego), `chainsaw` (motosierra) |
| `droplets` | `drop`, `ring`, `leaf`, `curl`, `dash` |
| `swoosh` | normal, varias hebras (`strands`), pintura (`paint_chance`), cruz (`cross`) |

## Observado en la referencia de pelea (`glowing/video_1.mp4`)

Análisis cada 4 fotogramas cruzando el video de referencia con los eventos detectados. Estado:
**✅** implementado y en el catálogo `pelea`, **🔜** pendiente.

| Seg. | Acción en el plano | Reacción en la referencia | Estado |
| --- | --- | --- | --- |
| 1.5–1.7 | Chocan de hombros al cruzarse | Descarga eléctrica de dos colores en el punto de choque | ✅ `body_bump → colision` (`clash`) |
| 1.9–2.4 | Tras el choque, se separan | Anillos y óvalos pequeños flotando alrededor de ambos | 🔜 partículas ambientales tras un choque |
| 3.2–4.1 | Se acomoda las gafas / mira al rival | Gafas que brillan; rayas cortas en los cristales | ✅ `lull`/`intent → gafas` (`eyewear`, solo a quien lleva gafas) |
| 4.3–4.8 | Agarra al rival del cuello | Rayos que recorren el brazo del atacante hasta el punto de agarre | 🔜 rayo a lo largo de la cadena del brazo |
| 4.8–5.2 | El agarrado queda quieto | Lenguas de fuego azul en el cuello y la cabeza del agarrado | 🔜 aura en la zona agarrada |
| 5.3–5.9 | Carga antes de golpear | Contorno de fuego en las manos y líneas de energía en el torso | 🔜 puños en llamas (`strike_windup`) |
| 5.8, 16.2, 18.1, 23.7, 25 | Golpe que conecta | Llamarada de pétalos y chispas | ✅ `person_contact → llamarada` |
| 6.3 | Golpe al aire | Proyectil de energía que cruza el cuadro | 🔜 proyectil |
| 6.7–7.0 | Patada giratoria | Arco alrededor de la pierna con puntos | ✅ `fast_swing → swoosh` (tobillos) |
| 7.2–7.5 | Postura de guardia | Óvalos que envuelven el cuerpo (aura de contorno) | 🔜 aura de cuerpo |
| 7.6–8.1 | Después de moverse | Gotas que caen al suelo | ✅ partículas `drop` |
| 7.6–8.9 | Pausa entre rondas; cada uno mueve una parte del cuerpo | Runa en el pecho del de negro, rayos en el brazo del de azul, gafas encendidas | ✅ `lull`, `intent → runa_pecho / rayos_brazo / gafas` |
| 9.0–9.3 | El golpe que sigue a la intención | Swoosh en cruz | ✅ `intended_strike → cruz` |
| 9.2, 16.4, 16.7, 18.8 | Brazo que barre | Swoosh de una o varias líneas | ✅ `fast_swing → swoosh` |
| 10.1, 16.9, 19.2 | Puñetazo que choca | Estallido en estrella de puntas | ✅ `clash`/`stars` |
| 10.4–10.7 | Golpeado aturdido | Remolino o nube garabateada alrededor de la cabeza | 🔜 aturdimiento |
| 13.5–13.7 | Pisotón | Anillo elíptico en el suelo bajo el pie | 🔜 onda en el suelo (`foot_strike`) |
| 13.9–14.4 | Juego de pies | Chispas naranjas en los pies | 🔜 chispas de pies |
| 14.4–14.7 | Mira al rival | Gafas que se encienden | ✅ parte de `rayo_ojos` |
| 14.7–15.7 | Lanza un golpe mirando al rival | **Rayo de los ojos** al rival; fuego al impactar | ✅ `fast_swing → rayo_ojos` (`beam`) |
| 14.7, 21.6, 26.3 | Choque de puños | Energía liberada, rayos de dos colores | ✅ `fist_clash → energia` (`clash`) |
| 17.6–17.9 | Golpe que conecta | **Estrellas** de cuatro puntas alrededor de la cabeza | ✅ `person_contact`/`fist_clash → estrellas` |
| 19.5–20.1 | Puños en guardia | Puños contorneados de fuego | 🔜 puños en llamas |
| 18.3, 21.0 | Trayectoria del puño | Contorno de "pintura" (forma barrida) | ✅ swoosh con `paint_chance` |
| 22.3–23.1 | Golpe recto sostenido | Brazo musculoso | ✅ `fast_swing → brazo_musculoso` (`arm_outline`) |
| 23.3–24.4 | Pulso sostenido, brazos extendidos | Llamas que suben sobre las cabezas | 🔜 columnas de energía en tensión |
| 24.7–26.0 | Se acercan con los puños listos | Puños que brillan antes del choque | 🔜 puños en llamas |
| 26.8–27.2 | Se van celebrando | Cintas de neón en el cielo | 🔜 cierre / celebración |

## Cómo crecer el catálogo

1. Con cada video de referencia nuevo, repetir el análisis: hoja de fotogramas cada 4 con los
   eventos detectados (ver `docs/comandos.md`) y anotar acción → reacción en una tabla como la de
   arriba.
2. Si la acción ya se detecta y el efecto ya existe, basta con añadir la opción al YAML.
3. Si falta el efecto, se implementa como un tipo nuevo del motor (`engine/`) y se añade al
   catálogo. Si falta la acción, se añade al análisis (`analysis/events.py`).
4. Un catálogo por tipo de escena (`pelea`, `baile`, `maquillaje`…). Los pesos se ajustan mirando
   `choreography.json` y la vista previa, no a ojo sobre el YAML.

## Espadas

Dos referencias de una persona sola con hojas y acrobacias. No es pelea (no hay rival), así que
los catálogos son propios: `espadas_neon` y `espadas_fuego`. Los dos piden `needs: [blades]`,
que enciende la detección de hojas en el análisis (apagada por defecto: ver más abajo).

```bash
vfxglow run --video <original>.mp4 --catalog espadas_neon
vfxglow run --video <original>.mp4 --catalog espadas_fuego
```

### video_38: neón cian y lima (10,6 s)

Dos hojas cortas (bastones negros) pintadas de neón: una cian y otra verde lima. La cámara se
mueve y hay tres escenarios (pared azul, gimnasio, espejo). Análisis cada 3 fotogramas.

| Seg. | Qué hace | Efecto en la referencia | Implementado |
| --- | --- | --- | --- |
| Todo | Sostiene las hojas | **Hojas pintadas de neón siempre**, una de cada color | ✅ `blade_glow`, por decisión solo en algunos tajos (`blade_swing → hoja_encendida`) |
| 0.2, 1.1, 4.3, 7.8 | Gira las hojas deprisa | **Copias fantasma** de la hoja flotando donde estuvo | ✅ `blade_echo` (siempre, solo con la punta rápida) |
| 0.8–1.5 | Tajos amplios | La hoja deja un rastro recto que se desvanece | ✅ parte de `blade_echo` |
| 1.9 | Patada | **Rayas de velocidad en el pie** | ✅ `fast_swing → pies` (swoosh en tobillos) |
| 2.0–2.3 | Mortal en el aire | Rayas cortas **sobre el cuerpo** | ✅ `flip → rayas` (`body_outline` en guiones) |
| 2.3, 4.2–4.5, 6.6, 7.4 | Aterriza / pisa fuerte | **Salpicadura en abanico** en el piso, amarilla | ✅ `landing → salpicadura` (`ground_burst`) |
| 3.1–3.5 | Patada giratoria / voltereta | **Contorno del cuerpo entero** en amarillo, y un **arco** grande | ✅ `flip → silueta` (`body_outline`), `blade_swing → arco` |
| 3.7, 3.9 | Tajo amplio | **Arco en media luna** que sigue la punta | ✅ `blade_swing → arco` (swoosh en `blade_*_tip`) |
| 7.2 | Pausa antes de atacar | **Cruz** amarilla sobre el pecho | ✅ `intent → cruz` (`intent_mark` `cross`) |
| 10.4 | Agachado, hoja abajo | **Venas de energía** dentro de la pierna | 🔜 rayos dentro del contorno |
| 5.5 / 9.6 | Corte de plano | La hoja sigue pintada en el plano nuevo | ✅ `blade_glow` no depende de eventos |

### video_39: fuego naranja y mirada magenta (5,8 s)

Dos katanas reales. Un solo color de fuego naranja; la mirada en magenta. Mucho más gráfico y de
dibujo animado que video_38. Los últimos 1,4 s no tienen efectos: la calma final es parte del
ritmo.

| Seg. | Qué hace | Efecto en la referencia | Implementado |
| --- | --- | --- | --- |
| 0.0–0.3 | Arranca, mira a cámara | **Banda magenta sobre los ojos** con un gancho: la mirada encendida | ✅ `entrance → mirada` (`eyewear` `band`) |
| Todo hasta 4.3 | Sostiene las katanas | Hojas pintadas de **fuego naranja** | ✅ `blade_glow`, por decisión solo en algunos tajos (`blade_swing → hoja_encendida`) |
| 0.5 | Tajo bajo | **Arco de fuego** con lenguas que salen del borde exterior | ✅ `blade_swing → tajo_fuego` (swoosh `flame`) |
| 0.6 | Tajo hacia arriba | Arco con **brasas** que caen | ✅ `tajo_fuego` + partículas `dash`/`leaf` |
| 0.7–1.3, 2.2–3.5 | Saltos y volteretas | **Silueta de fuego** en casi cada voltereta | ✅ `flip`/`jump → silueta` (85%) |
| 1.3–1.8 | Aterriza tras el giro | **Raya larga y recta en el piso** | ✅ `landing → raya_piso` (`floor_streak`) |
| 1.6–2.0 | Patada alta | **Bolas de fuego** que siguen la pierna, más grandes cerca del pie | ✅ `fast_swing → bolas_fuego` (swoosh `dots`) |
| 3.7–3.9 | Clava las hojas en el piso | **Nube de humo de dibujo animado** que rodea los pies | ✅ `blade_ground → nube` (`ground_cloud`) |
| 4.4–4.5 | Apoya las puntas en el piso | **Estallido blanco con borde naranja** en cada punta | ✅ `blade_ground → estallido` (`ground_burst`) |
| 4.6–5.8 | Se levanta, mira a cámara | Nada: las katanas ya sin pintar | ✅ natural: sin eventos no hay efectos |

### Detección de hojas (`analysis/blades.py`)

Por cada mano: la recta fina más plausible cerca de la mano (mapa de crestas + Hough), filtrada
por cuatro reglas — pasa por la mano, no va hacia el codo (antebrazo), no sigue del otro lado de
la empuñadura (raya del piso) y no sale de la zona de búsqueda. Dirección del agarre por la línea
de los nudillos. Luego, por mano: se descartan saltos de largo o de ángulo, se rellenan huecos de
hasta 8 fotogramas con el largo típico y se suaviza el ángulo.

Medido sobre el tramo de katanas sin pintar de video_39 (4,4–5,8 s): bien con las hojas
separadas del cuerpo (5,4–5,8 s); falla con las hojas verticales apoyadas en el piso, donde la
raya blanca del suelo pasa justo por las manos. **No sirve para decidir si hay espada**: en la
pelea de video_1 encuentra "líneas" en el 78% de las manos (brazos, ropa, fondo), igual que en
los videos de espadas. Por eso está apagada por defecto y la enciende el catálogo. Mejoras en
[pendientes.md](pendientes.md).

## Baile

Dos referencias de baile con un lenguaje distinto al de pelea: **lo que más se mueve se enciende**.
Catálogos `baile_neon` (solista, video_33) y `baile_duo` (pareja, video_34).

```bash
vfxglow run --video ../glowing/data/original/video_33.mp4 --catalog baile_neon
vfxglow run --video "../glowing/data/original/video_34 (1).mp4" --catalog baile_duo
```

### El neón de estas referencias (aplicado a todo el motor)

Medido sobre los píxeles pintados de video_33: la línea es casi blanca y el color vive en el
resplandor, con un núcleo de 2,7–3,8 px a 720 de ancho. `neon_layers` (engine/swoosh.py) dibuja,
de fuera hacia dentro:

- Dos halos **desenfocados** del color (como las `box-shadow` de un neón en CSS), de 8x y 3,5x
  el núcleo.
- Un borde de color nítido de 2x.
- Un núcleo blanco al 90%, de grosor fijo según la resolución: 0,5% del ancho del cuadro
  (≈3,6 px a 720), con extremos redondos.

Afecta a todos los efectos de línea (swoosh, llamaradas, gafas, hojas, siluetas...). Dos
detalles del raster lo hacen posible:

- El alfa de cada trazo atenúa de verdad su energía (antes Skia devolvía píxeles sin
  premultiplicar y el alfa casi no contaba).
- La ganancia HDR solo empuja el color: el blanco queda cerca de 1, así que el bloom no
  convierte el núcleo en una mancha.

Las partes del cuerpo encendidas usan **dos pasadas**, como haría un editor: una capa con
`blend: tint` que tiñe la piel o la ropa conservando su luz (piel verde, pantalón cian) y otra
`add` con el borde blanco y su halo encima.

### video_33: solista, cada tramo una parte del cuerpo

| Seg. | Qué se mueve | Efecto en la referencia | Implementado |
| --- | --- | --- | --- |
| 0.0–2.4 | Brazo extendido con la gorra | Brazo y gorra teñidos de verde, con contorno blanco | ✅ `spotlight` → `body_glow` del brazo; la gorra con `prop_outline` (contorno exacto de SAM 2) |
| 0.0–9.0 | La gorra pasa de mano en mano | Gorra teñida y contorneada mientras se mueve | ✅ `prop_outline` siempre activo + `prop_transfer → doble_contorno` |
| 0.6–1.3 | Traspaso de mano a mano | Resorte de la gorra a la mano que la recibe | ✅ `prop_transfer → resorte` (`prop_spring`) |
| 2.3–3.4 | La gorra gira en las manos | Anillo que sube y baja por la gorra, gorra teñida | ✅ `prop_spin → anillos` (`prop_rings` + tinte) |
| 3.3–4.1 | Termina de girar | Oreja puntiaguda y corazoncito sobre la gorra | ✅ `prop_doodle` (`anchor: end`) |
| 4.0–6.4 | Torso de frente | Torso magenta con **abdominales y pectorales dibujados** | ✅ `spotlight → torso_abdominales` (`shapes: [abs]`) |
| 6.6–7.3 | Se pone la gorra | Gorra dibujada en neón sobre la cabeza, cara de caricatura | ✅ `prop_worn → gorra_puesta` (contorno real + `face_toon caricature`) |
| 8.2–9.2 | Mano en la cara y la aparta | Ojos con pestañas, labios de beso; los labios viajan a los dedos | ✅ `face_touch → beso` (`face_toon kiss` + jalón) |
| 9.3–10.3 | Brazo flexionado arriba | **Brazo musculoso** verde | ✅ `body_glow` del brazo con `shapes: [biceps]` |
| 10.8–11.3 | Pecho quieto | **Collar** con dije sobre el cuello | ✅ `adornment` `necklace` |
| 12.1–13.1 | Mirada a cámara | Gafas y ojos en X dibujados | ✅ `cabeza_gafas` (`eyewear`) |
| 14.0–14.9 | Torso que gira | Torso amarillo con abdominales | ✅ `torso_abdominales` |
| 18.6–20.0 | De espaldas | Espalda teñida con un símbolo | ✅ tinte de torso (el símbolo concreto, 🔜) |
| 20.8–22.3 | Pecho al frente | **Estrellas en el pecho** que titilan | ✅ `adornment` `chest_stars` |
| 24.0–24.8 | Piernas abiertas | Pantalón cian con contorno blanco | ✅ `spotlight → piernas` |
| 27.2 | Barrido del brazo | Estela blanca gruesa | ✅ `fast_swing → estela` (modo pintura) |
| 28.1–28.7 | Cadera | **Sombrero vaquero** y cinturón dibujados | ✅ sombrero; cinturón 🔜 |

### video_34: pareja, un color por persona

| Seg. | Efecto en la referencia | Implementado |
| --- | --- | --- |
| 0.0–1.5 | Aureolas sobre la cabeza y ojos encendidos | ✅ `entrance → aureola` (`adornment halo` + `eyewear glint`) |
| 5.2–6.1 | Notas musicales que salen de las manos | ✅ partículas `note` |
| 19.2–20.7 | Corazones que salen de las manos | ✅ partículas `heart` |
| 9.9–10.5 | Contorno de la chaqueta | ✅ `spotlight → contorno` (solo borde, `fill: 0`) |
| 14.5–15.6 | Rayo que recorre el cuerpo | ✅ `fast_swing → rayo` |
| 24.1–25.5 | Rodillas que brillan | ✅ `spotlight → rodillas` (`knee_dots`) |
| 33.7–34.5 | Rayas en las piernas y bandas en los tobillos | ✅ `spotlight → tobillos` (`ankle_bands`) |

### Objeto protagonista (`needs: [props]`)

En los segundos 0–9 de video_33 la gorra es la protagonista: pasa de una mano a la otra, vuela y
acaba en la cabeza. `analysis/props.py` la sigue con dos modelos:

1. **Grounding DINO** (`a baseball cap. a hat.`) encuentra la caja, incluso boca arriba o tapada
   por la mano. Mientras no hay objeto, la busca cada 5 fotogramas; después, cada 30 comprueba
   que SAM 2 sigue sobre ella y la vuelve a sembrar si no.
2. **SAM 2** (`facebook/sam2.1-hiera-tiny`, modo video en streaming) recorta el contorno exacto
   y lo propaga de un fotograma al siguiente.

Para volver a sembrar SAM 2 hacen falta dos cosas: confianza de 0,4 o más y el **color** de la
gorra, aprendido en los primeros 60 fotogramas seguros. Cuando la gorra sale volando del cuadro
(seg. 27,5), Grounding DINO llama "hat" al pelo (0,48) y a un zapato (0,35); por distancia de
color (Bhattacharyya H-S) la gorra da 0,36–0,47, el zapato 0,73 y el pelo 0,89, y el corte está
en 0,6. Si Grounding DINO no la ve en 3 comprobaciones seguidas, se da por perdida y se borran
esos fotogramas.

Coste medido en MPS: ~1,2 s por fotograma (unos 18 min para los 903 de video_33). Queda en la
caché del análisis.

Cada fotograma recibe un estado según las manos y la cabeza de la pose: `left`, `right`, `both`,
`air`, `worn` (puesta) o `fitting` (en la cabeza con una mano encima). Los cambios de estado
dan dos eventos:

- `prop_transfer`: el objeto pasa de una mano a la otra (kind `left_to_right` /
  `right_to_left`), aunque pase por las dos manos o por el aire hasta 1 s.
- `prop_worn`: llega a la cabeza (kind `fit` con una mano encima, `drop` si cae solo).

El efecto `prop_outline` pinta ese contorno: relleno de tinte (`fill`, con `blend: tint`) y
contorno de neón. Formas: `double` (segundo contorno), `no_outline` (solo relleno) y `worn` (lo
pinta también puesto; por defecto no, porque puesta deja de ser protagonista).

El objeto se cambia con `prop:` en el catálogo o con `analysis.props.query` en la configuración.

**Resorte** (`prop_spring`, seg. 0,6–1,3 de la referencia): durante un `prop_transfer`, un cordón
en espiral visto de lado une la gorra con la **mano que la va a recibir**. Se estira hasta quedar
recto cuando la mano está a 1,6 torsos o más y se comprime con bucles grandes al llegar la gorra.
`rings` fija los bucles (5) y `size` su radio comprimido en torsos (0,16). Se adelanta al evento
con `trigger.lead` (10 fotogramas), porque en la referencia aparece antes de soltar la gorra;
por la misma razón, el foco del capítulo de un traspaso empieza 0,35 s antes.

**Anillos** (`prop_rings`, seg. 2,3–3,4 de la referencia): mientras la gorra gira en las manos, un
anillo elíptico la recorre subiendo (color principal del capítulo) y bajando (acento), con la
mitad de atrás tenue como si la tapara la gorra. Viaja por el eje de la gorra más cercano a la
vertical, así que con la gorra de frente sigue siendo horizontal. Mientras gira, el contorno
permanente se aparta (`Prop.spinning`) y la gorra solo se tiñe.

El giro lo detecta el análisis (`prop_spin`): el contorno cambia de orientación, excentricidad o
área de forma sostenida (media de 9 fotogramas sobre 10, al menos 0,4 s) con la gorra en las
manos, sin contar los fotogramas de un traspaso. En video_33 marca 40–104 (los anillos de la
referencia están en 70–103) y 791–809.

**Oreja y corazoncito** (`prop_doodle`, seg. 3,3–4,1): al terminar de girar, a la gorra le sale
una oreja puntiaguda en el extremo de arriba de su eje y un corazoncito al costado (`horn`,
`ears`, `heart`). Se enciende al **final** del giro con `trigger.anchor: end`: la ventana empieza
cuando el evento termina y dura `hold`.

**"Ajustado"** (`prop_worn → gorra_puesta`, seg. 6,9–7,2): con la gorra recién puesta, la cara se
tiñe y se dibuja como caricatura (`face_toon`, forma `caricature`: mandíbula, orejas, ojos de
punto, nariz y boca).

**Cara de caricatura y "jalón"** (`face_touch → beso`, seg. 8,2–9,2): la mano en la cara la vuelve
caricatura (`face_toon`, forma `kiss`: ojos cerrados con pestañas y labios de beso, con la cara
teñida). Cuando la mano se aparta, en 0,3 s los labios viajan hasta los dedos (de lado, como un
"3") y los ojos se estiran en rayas hacia la mano.

`face_toon` usa los puntos de la cara **de la pose** y no la malla facial: con la gorra puesta y
la mano encima, Face Mesh se pierde justo ahí (fotogramas 205–260 de video_33).

El toque (`face_touch`, `analysis/touch.py`) es una punta de dedo a menos de 0,6 tamaños de cara
(distancia entre orejas) del centro de la cara durante al menos 0,25 s. No cuenta la mano que
sostiene la gorra ni la que se la acomoda puesta (dedos sobre su contorno). En video_33 marca
256–268, el beso de la referencia.

### Color por capítulo (`chapters: true`)

En la referencia el color no salta en cada efecto: gorra y brazo van en verde mientras ese es el
foco, y todo pasa a magenta cuando el foco cambia al torso. Con `chapters: true` el coreógrafo
divide el video en **capítulos** y guarda en el guion (`chapters`) dos colores para cada uno
(principal y acento). Todos los efectos con paleta toman esos colores; uno disparado por un
evento conserva el del capítulo en que empezó.

- Un capítulo empieza cuando cambia el foco: un `spotlight` de otra parte del cuerpo, o la gorra
  (`prop_transfer` → foco `prop`, `prop_worn` → foco `prop_worn`).
- Dura al menos `chapter_min_s` (0,8 s): un foco que llega antes se ignora, salvo el de la gorra,
  que se queda con el capítulo.
- Dos capítulos seguidos nunca repiten el color principal.

### Línea de atención (`attention: true`)

Principio P1 de `docs/criterio_de_analisis.md`: nada compite con el protagonista.
`analysis/attention.py` decide por fotograma quién manda: un brazo, las piernas, la cabeza, el
torso o el objeto. Admite un segundo foco si otra región, alejada, también destaca.

Reglas:

- **Cuerpo:** cada parte se compara con lo que suele moverse ella misma.
- **Objeto:** en las manos le gana al brazo que lo sostiene, y el movimiento de esa mano cuenta
  como movimiento del objeto.
- **Cabeza:** manda con la mano en la cara, con el objeto recién puesto y cuando todo el cuerpo
  está quieto (la mirada).
- **Transferencia:** al soltar la cara, el brazo de esa mano hereda el foco.
- **Estabilidad:** histéresis para que el foco no parpadee; tramos de al menos 0,4 s.

Con `attention: true` en el catálogo:

1. Los `spotlight` salen de la línea de atención (trozos de ~1,2 s del primer y el segundo foco),
   así que se enciende lo que manda.
2. El motor apaga con un fundido corto todo efecto cuya región (`engine/focus.py`) no esté en foco
   en ese momento. `style.focus: false` lo exime.

Medido en video_33:

| Tramo | Foco |
| --- | --- |
| 0-6,7 s | La gorra |
| 6,8-8 s | La cabeza (gorra puesta) |
| 8,7-9,5 s | La cabeza (beso) |
| 9,5-12,4 s | El brazo derecho (la energía sale de la cara) |
| 16,4-19,5 s | La gorra |
| 21-26 s | Las piernas |
| 26,5-28 s | La gorra y las piernas a la vez |

### Frente o espalda (P6)

`body_glow` con `abs` mira hacia dónde está la persona (`facing`, por el orden de los hombros en
largos de torso: de frente el izquierdo queda a la derecha de la imagen):

| Orientación | Dibujo |
| --- | --- |
| De frente | Pectorales y abdominales |
| De perfil | Nada |
| De espaldas | Músculos de la espalda (`back_lines`) o una figura de relleno al centro (`badge`: radiactivo, sol, estrella, corazón, espiral), sorteada por activación |

En video_33 la espalda se detecta en 18,8–20,2 s, como en la referencia.

- `partial` dibuja solo el 40–70% de las líneas (seg. 14,6 de la referencia).
- `lines_only` omite el contorno de la parte y deja solo las líneas interiores.

### Colores según el tono de piel

El análisis mide el tono de piel de cada persona (`analysis/skin.py`: mejillas y, si la cara no
alcanza, el pecho; solo píxeles en rango de piel, sin ropa negra ni rojos saturados) y lo guarda
en el brief (`skin`). Para análisis anteriores, el pipeline lo mide al vuelo antes de dirigir.

Una parte teñida queda en `(0,15 + 2 × luma de la piel) × tono`. `director/palette.py` puntúa
cada color por el contraste de la línea blanca con esa piel teñida y porque el tinte no quede
apagado, y el coreógrafo lo usa como peso (al cuadrado) al sortear colores: en capítulos y en
`palette_weights` de cada efecto. Ningún color queda fuera, solo sale menos.

| Piel (luma) | Salen más | Salen menos |
| --- | --- | --- |
| Clara (~0,3, video_33) | magenta, violeta, rosa (72%) | amarillo, turquesa, verde |
| Morena (~0,07, video_34 persona 0) | verde, turquesa, amarillo (66%) | magenta, violeta |

### Opciones que ceden el paso (`yields_to`)

Una opción puede ceder ante otra acción cercana: si a menos de `yield_window_s` (1,5 s) hay una
de las acciones de `yields_to`, con probabilidad `yield_chance` (0,75) no sale. En `baile_neon`
los accesorios de cabeza ceden ante `prop_worn` y `face_touch`, para no tapar la caricatura de la
gorra puesta ni el beso; al azar, a veces sí coinciden.

### Cómo se elige la parte (`spotlight`)

Por tramos de 1,2 s y por persona se mide el recorrido de cada parte (brazo izquierdo, brazo
derecho, piernas, pies, cabeza, torso) en torsos, y se divide por su recorrido habitual en todo
el video: gana la parte que se mueve **más de lo normal**, no la que más se mueve en absoluto
(los brazos siempre recorren más que la cabeza). El catálogo elige el efecto según esa parte
(`kinds`).
