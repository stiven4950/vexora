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
| `intent_mark` | `rune`, `rays`, `halo`, `spiral`, `sparkle` |
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
