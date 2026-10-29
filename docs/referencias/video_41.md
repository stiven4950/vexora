# video_41 · Solista con objetos, caras y energía en los brazos

Lectura de la referencia `glowing/video_41.mp4` contra su original `original/video_41.mp4` (los dos
640×800, 30 fps, 676 fotogramas, 22,5 s, sin corrimiento entre ellos), hecha con el criterio de
`docs/criterio_de_analisis.md`. La luz añadida se aisló restando el original (gris dilatado 5 px,
umbral 25) y se revisó cada 0,1 s.

Un solo bailarín con chaqueta deportiva color menta, pantalón negro y tenis blancos, en una calle. Al
principio camina hacia la cámara; después baila en el sitio, casi todo con los brazos a la altura del
pecho y la cabeza.

Ojo con la medición: la chaqueta es casi del mismo color que el neón, así que la resta marca falsos
positivos en los bordes de la chaqueta cuando él se mueve rápido (6,9, 8,4, 16,8, 18,8, 20,8). Lo
que se describe abajo está confirmado a ojo en la referencia.

## La intención del creador

1. **Un objeto en la mano cuenta la entrada**: bebe de una botella (0-1,7) y luego sostiene algo que
   revienta en una nube (4,9-5,9).
2. **Mientras camina, cada paso es un tajo**: bandas diagonales que cruzan el torso de hombro a
   cadera (2,0-4,1).
3. **Cuando baila, la energía vive en los brazos**: contornos, rellenos y tramos punteados que corren
   por el antebrazo y saltan de un brazo al otro siguiendo al que se mueve (6,0-11,9 y 18,0-21,7).
4. **Cuando las manos van a la cara, la cara se vuelve una máscara**: calavera con ojos en X (12,1),
   cara de burla con la lengua afuera (16,2), cara de asombro con ojos redondos (21,9).
5. **Un solo color** (cian sobre blanco) y casi sin huecos: un efecto cada 0,2-0,5 s.

## Tabla por momento

Estado: ✅ ya lo hacemos · 🟡 hay algo parecido · ❌ nuevo · ❓ no está claro qué significa.

| Seg. | Qué hace la persona | Referencia | Estado |
| --- | --- | --- | --- |
| 0,0-0,4 | Sostiene algo frente a la cintura | **Botella de neón llena** (contorno con tapa, relleno blanco = líquido) en la mano | ❌ |
| 0,5-0,9 | Se la lleva a la boca e inclina la cabeza | **Bebe**: la botella se inclina con la mano y el líquido se mueve hacia la boca | ❌ |
| 1,0-1,2 | Baja la botella | **El nivel bajó**; quedan burbujas sueltas dentro | ❌ |
| 1,3-1,4 | La aprieta | **Botella vacía** y luego **arrugada** (el contorno se dobla) | ❌ |
| 1,5-1,7 | Suelta la mano | **La botella se desdibuja** hasta desaparecer (los trazos se rompen en manchas que se apagan) | ❌ |
| 1,9 | Empieza a caminar | Raya corta en el hombro | 🟡 |
| 2,0-2,4 | Paso | **Tajo**: banda blanca gruesa que cruza el torso del hombro izquierdo a la cadera derecha, se desliza hacia abajo y sale por la mano | ❌ |
| 2,5-3,0 | Paso | Otro tajo igual | ❌ |
| 3,1-3,5 | Paso | Otro tajo | ❌ |
| 3,7-4,1 | Paso | Otro tajo, que acaba en la mano | ❌ |
| 4,2-4,8 | Se detiene, se planta | Nada | — |
| 4,9 | Sube la mano derecha | Destellos en el brazo y la cara | 🟡 |
| 5,0 | Mano al frente | **Un aerosol o extintor pequeño** en la mano | ❌ |
| 5,1-5,6 | Lo apunta | **Rocía**: una nube blanca que sale de la boquilla y crece (también se lee como un **flash de cámara**) | ❌ |
| 5,7-5,8 | — | La nube se abre hacia afuera con salpicaduras | ❌ |
| 5,9 | — | Queda una nube redonda y una espiral en la mano | ❌ |
| 6,0 | Mano al hombro | **Bola de luz** en el hombro | 🟡 |
| 6,1-6,6 | Baja el brazo | La bola se vuelve el **contorno del brazo** con la mano dibujada (los dedos), solo el borde de adentro y el de afuera | ✅ `body_glow` brazo |
| 6,7-7,1 | Abre el otro brazo | **La línea cruza el cuerpo**: baja por el cierre de la chaqueta y sube por el otro brazo hasta la mano | ❌ |
| 7,20-7,27 (f6-f8) | Mano derecha abierta | Tramos punteados por el antebrazo y contorno de la mano | ✅ |
| 7,30-7,43 (f9-f13) | Cierra la mano | **El contorno se recoge en una pelota** en la palma | ❌ |
| 7,47-7,53 (f14-f16) | Lanza la mano al otro lado | **La pelota se deforma con la velocidad**: se aplasta en un óvalo que viaja con la mano | ❌ |
| 7,57-7,63 (f17-f19) | Llega a la otra mano | La pelota se vuelve un **gancho** ("C") en la mano izquierda: gancho de la muerte | ❌ |
| 7,67-7,90 (f20-f27) | Brazos cruzados que se abren | **El contorno viaja** por el antebrazo izquierdo hasta el brazo extendido | ❌ |
| 8,2 | Brazos frente al pecho, cabeza erguida | **Cabeza de perfil dibujada en línea**: contorno de la cabeza, la oreja y el cuello | ❌ |
| 8,3-8,8 | Manos que se cruzan frente al pecho | **Guantes de neón**: contorno de la mano con los dedos, que pasa de una mano a la otra | 🟡 |
| 8,9-9,0 | Sube el brazo | Contorno del brazo levantado, relleno | ✅ |
| 9,1-9,6 | Brazo arriba, el otro cruzado | **Líneas de la chaqueta**: el cierre y el borde de abajo (una "L"), que se vuelven punteadas | 🟡 `jacket` |
| 9,7-10,0 | Brazo cruzado sobre la cara | Contorno del brazo y la mano | ✅ |
| 10,0-11,3 | Antebrazo vertical frente a la cara | **Barra de carga en el antebrazo**: tramos y guiones que suben y bajan por el antebrazo, como una tira de LED | ❌ |
| 11,3-11,5 | Manos juntas frente a la cara | Manos rellenas de luz | 🟡 |
| 11,6-11,9 | Sube la mano | **Guante de neón** en la mano levantada | 🟡 |
| 12,0 | Mano a la cabeza | Destello en la mano y el pecho | 🟡 |
| 12,1-12,9 | Mano sobre la cabeza, la otra abajo | **Calavera**: contorno de la cara con **ojos en X** y una sombra de boca | 🟡 `face_toon` |
| 13,0-13,2 | Pone la mano sobre la calavera | **La mano gana el protagonismo**: la calavera se apaga y se contornea la mano con los dedos | ❌ |
| 13,3-13,9 | Juego de manos por encima de la cara | **Pase de energía de una mano a la otra**: una raya que salta entre las manos y las sigue | ❌ |
| 14,0-14,1 | Manos juntas sobre la cabeza que se separan | **Abanico que se abre** sobre la cabeza | ❌ |
| 14,2-14,8 | Estira los brazos arriba | **Brazos rellenos de luz** que suben y se doblan | 🟡 |
| 14,9-15,0 | Baja las manos a la cara | Raya vertical sobre la cara | 🟡 |
| 15,1-15,4 | Manos en la cara | **Aro horizontal que gira alrededor de la cabeza** | 🟡 aureola |
| 15,5-15,6 | — | El aro se deforma | 🟡 |
| 15,6-15,9 | Mueve las manos de lado a lado sobre la cara | **Una línea por mano** (no el contorno): las dos forman un triángulo que se abre y se cierra con las manos | ❌ |
| 16,0-16,1 | Manos a los lados de la cara | La cara se llena de luz | 🟡 |
| 16,2-16,3 | **Se destapa la cara** | **Cara de burla**: ojos en X y **lengua afuera** | ❌ (`face_toon` no tiene lengua) |
| 16,4 | — | Ojos enojados y boca pequeña | 🟡 |
| 16,5-16,7 | Manos bajan al pecho | **Sopla una burbuja** que sale de la boca y crece | ❌ |
| 16,8-17,6 | Manos en el pecho, una arriba y otra abajo | **Maneja la burbuja con las manos**: la sostiene, la pasa de una mano a la otra, gira | ❌ |
| 17,7-17,9 | Abre las manos | La burbuja se estira en un arco grande que sigue la mano | ❌ |
| 18,00-18,13 (f0-f4) | Brazos horizontales, uno sobre otro, que se deslizan | **Ola u objeto flotante** bajo el antebrazo, que él lleva o hala hacia la izquierda | ❌ |
| 18,20-18,33 (f6-f10) | Cambia de dirección | **Se va por la mano derecha y aparece del otro lado arqueado** | ❌ |
| 18,40-18,93 | Repite el vaivén | La ola vuelve a cruzar (izquierda, sale por la mano, reaparece arqueada) | ❌ |
| 19,07-19,27 | Brazos en "X" | La ola reaparece como un **remolino** en la mano y sale hacia afuera | ❌ |
| 19,3-19,9 | Antebrazos cruzados | Líneas que corren por los antebrazos | 🟡 |
| 20,0-20,9 | Mueve los brazos frente al pecho y la cara | **Partes del cuerpo pintadas** (pecho, antebrazo, mano) y **transición** de una a otra, siempre hacia la parte que toma el protagonismo | ❌ |
| 20,90-21,13 | Mano extendida | Mano contorneada | ✅ |
| 21,17-21,37 | Desliza una mano por el otro brazo | Arco y tramos punteados por el antebrazo | 🟡 |
| 21,40-21,73 (f12-f22) | Sigue deslizando, hacia arriba | **Flechas "^"** que se dibujan en el antebrazo en la dirección del deslizamiento | ❌ |
| 21,77-21,83 (f23-f25) | La mano llega a la cabeza | Las flechas suben y **se convierten en la máscara**: el contorno de la cara | ❌ |
| 21,90-22,5 (f27 en adelante) | Mano al mentón, mira a la cámara | **Máscara de asombro**: contorno de la cara, ojos redondos grandes con pupilas, boca pequeña. Sigue a la cara al girar | 🟡 `face_toon` |

## Inventario de efectos

### Nuevos

1. **Botella que se bebe** (0-1,7). Objeto de neón en la mano con el líquido como relleno: se inclina
   hacia la boca, el nivel baja, quedan burbujas, al final vacía y arrugada, y **se desdibuja hasta
   desaparecer**. Detección: mano junto a la boca con la cabeza hacia atrás. Va con `hand_props.py`,
   igual que fumar y beber de unpair_dance. Variantes: lata que se aplasta, vaso, cartón de jugo con
   pajilla.
2. **Tajo en cada paso** (2,0-4,1). Mientras camina hacia la cámara, cada paso dispara una banda ancha
   que cruza el torso en diagonal y sale por la mano. Detección: `step_events` mientras se acerca.
   Variantes: la banda en la otra diagonal con el otro pie, o una "X" cuando da dos pasos seguidos.
3. **Línea que cruza el cuerpo de un brazo al otro** (6,7-7,1). El contorno de un brazo baja por el
   cierre de la chaqueta y sube por el otro brazo cuando ese brazo empieza a moverse. Es la
   transferencia de P3 dibujada sobre la ropa.
4. **Barra de carga en el antebrazo** (10,0-11,3). Antebrazo quieto y vertical: tramos de luz que
   suben y bajan por él como una tira de LED o una barra que se llena. Variantes: anillos que suben,
   un indicador que se llena hasta la mano y destella.
5. **Cabeza de perfil en línea** (8,2). Contorno de la cabeza, la oreja y el cuello cuando la cara se
   ve de lado.
6. **Cara de burla con la lengua afuera** (16,2-16,3). Al destaparse la cara: ojos en X y lengua.
   Una expresión más para `face_toon`.
7. **Contorno que viaja** (7,67-7,9 y 6,7-7,1). El contorno de una parte del cuerpo se transmite a otra
   (de un antebrazo al brazo extendido, de un brazo al otro por el cierre).
8. **Máscara de calavera con ojos en X** (12,1-12,9): ver "Parecidos".
9. **Aerosol o extintor pequeño** (5,0-5,9). Objeto en la mano extendida que rocía una nube blanca que
   crece y se abre con salpicaduras. Variante: **flash de cámara** (destello blanco que llena el
   cuadro desde la mano y se apaga).
10. **Pelota que se deforma con la velocidad y se vuelve gancho** (7,3-7,6). El contorno de la mano se
    recoge en una pelota; cuando la mano se mueve rápido, la pelota se aplasta en un óvalo en la
    dirección del movimiento; al llegar a la otra mano se vuelve un gancho ("gancho de la muerte").
11. **Pase de energía entre las manos** (13,0-13,9). Con una máscara puesta, la mano que se pone
    encima toma el protagonismo: la máscara se apaga, la mano se contornea y la energía empieza a
    saltar de una mano a la otra mientras juegan sobre la cara.
12. **Abanico que se abre** (14,0-14,1). Manos juntas que se separan sobre la cabeza.
13. **Una línea por mano** (15,6-15,9). Cuando las manos se mueven de lado a lado, no se contornean:
    se dibuja una línea por mano y las dos forman un triángulo que se abre y se cierra con ellas.
14. **Burbuja soplada que se maneja con las manos** (16,5-17,9). Sale de la boca, crece, se sostiene y
    se pasa entre las manos, y al final se estira en un arco.
15. **Ola que se hala** (18,0-19,3). Un objeto flotante bajo el antebrazo que va y viene con él; cuando
    cambia de dirección, se va por la mano y reaparece del otro lado arqueado. Acaba en un remolino.
16. **Partes pintadas con transición** (20,0-20,9). Se pinta de neón la parte del cuerpo que tiene el
    protagonismo y el relleno viaja a la siguiente cuando el foco cambia.
17. **Flechas que se vuelven máscara** (21,4-21,9). La mano que se desliza por el otro brazo deja
    flechas en la dirección del movimiento; cuando llega a la cabeza, las flechas se convierten en
    el contorno de la cara y en la máscara.

### Parecidos a lo que ya hay (afinar)

- **Guantes de neón** (8,3-8,8, 11,6-11,9): contorno de la mano con los dedos, que salta de una mano a
  la otra.
- **Calavera con ojos en X** (12,1-12,9) y **cara de asombro con ojos redondos** (21,9-22,5) en
  `face_toon`: aquí la cara se contornea entera, no solo los rasgos.
- **Aro que gira alrededor de la cabeza** (15,1-15,4) cuando las manos tapan la cara.
- **Líneas de la chaqueta** (9,1-9,6): el cierre y el borde de abajo, no el contorno completo.
- **Mano contorneada tapando la cara** (13,0-13,2).

## Patrones

1. **Caminar = tajos, bailar = brazos.** El tipo de movimiento decide la familia de efectos.
2. **La cara manda cuando las manos la tocan.** Cada vez que las manos van a la cara, sale una
   máscara o una expresión, y se apaga cuando las manos se van.
3. **La energía salta al brazo que se mueve.** Nunca están los dos brazos encendidos con efectos
   distintos: el efecto pasa de uno al otro.
4. **El objeto tiene vida**: la botella se vacía y se arruga; el objeto de 5,0 se llena y revienta.
5. **Cierre con la cara**: el video acaba con una expresión sobre la cara, no con partículas.
6. **Las manos le ganan a la cara.** Si la mano se pone encima de una máscara, la máscara se apaga y
   el efecto pasa a la mano (13,0).
7. **Cuando las manos se mueven rápido, menos dibujo**: una línea por mano en vez del contorno (15,6);
   la pelota se deforma en vez de mantener la forma (7,5).
8. **Lo que sale por un lado entra por el otro**: la ola se va por la mano y reaparece del otro lado
   (18,2); las flechas suben por el brazo y se vuelven la máscara (21,8).
9. **Todo lo que aparece se va desdibujándose** (la botella, 1,5-1,7), no de golpe.

## Preguntas resueltas

- **1,5-1,7**: la botella se desdibuja hasta desaparecer.
- **5,0-5,9**: aerosol o extintor pequeño; también se lee como un flash de cámara.
- **7,3-7,9**: gancho de la muerte, o una pelota que se deforma con la velocidad de la mano; el
  contorno de partes del cuerpo se transmite de un lugar a otro.
- **13,0-13,9**: con la calavera puesta, la mano encima gana el protagonismo, se contornea y empieza
  el pase de energía entre las manos.
- **14,0-14,1**: un abanico que se abre.
- **15,6-15,9**: una línea por mano, como un triángulo que se abre y se cierra.
- **16,5-17,9**: una burbuja que sale de la boca y luego maneja con las manos.
- **18,0-19,3**: una ola u objeto flotante que hala de un lado a otro; se va por la mano derecha y
  aparece del otro lado arqueado.
- **20,0-21,9**: partes del cuerpo pintadas con transición hacia la parte que recibe el
  protagonismo; al deslizar una mano por el brazo, flechas en la dirección del movimiento, que
  terminan en la máscara (21,9, f27).

## Qué se implementó

| Efecto de la referencia | Forma (`style.shapes`) | Opción del catálogo `baile` |
| --- | --- | --- |
| Botella que se bebe (0-1,7) | `water_bottle`, `beer`, `can` | `hand_mouth`: botella, cerveza, lata |
| Tajo en cada paso (2,0-4,1) | `walk_slash` | `step`: tajo |
| Aerosol o flash (5,0-5,9) | `spray_can`, `camera_flash` | `point`: aerosol, flash |
| Línea por el cierre de un brazo al otro (6,7-7,1) | `zipper_line` | `spotlight`: linea_cierre |
| Pelota que se aplasta y se vuelve gancho (7,3-7,6) | `hook_ball` | `fast_swing`: gancho |
| Cabeza en línea (8,2) | `profile_head` | `spotlight`: cabeza_perfil |
| Barra de carga en el antebrazo (10,0-11,3) | `charge_bar` | `spotlight`: barra_carga |
| Calavera, burla, asombro (12,1; 16,2; 21,9) | `skull`, `prank`, `shock` (`face_toon`) | `hands_on_head`: calavera; `cover_eyes`: burla; `face_touch`: asombro |
| Pase de energía entre las manos (13,0-13,9) | `hand_volley` | `hands_on_head`: pase_manos |
| Abanico (14,0) | `fan` | `hands_on_head`: abanico |
| Una línea por mano en triángulo (15,6-15,9) | `hand_lines` | `cover_eyes`: lineas_manos |
| Burbuja soplada (16,5-17,9) | `bubble_blow` | `hand_mouth`: burbuja_soplada |
| Ola que se hala (18,0-19,3) | `wave_pull` | `spotlight`: ola_brazo |
| Partes pintadas con transición (20,0-20,9) | `paint_relay` | `spotlight`: parte_pintada |
| Flechas que se vuelven máscara (21,4-21,9) | `arrows_mask` | `spotlight`: flechas_mascara |

## Calco de la referencia

`configs/pruebas/video_41_referencia.yaml` fija 32 momentos, cada uno con su efecto, segundo,
duración y lado. Los tiempos y los lados se afinaron en tres vueltas con
`tools/compare_reference.py`: en cada tramo que no coincidía se midió en qué parte del cuerpo
dibuja la referencia y en cuál nosotros.

| Vuelta | Presencia (dibujamos donde la referencia dibuja) | Misma parte del cuerpo |
| --- | --- | --- |
| 1: la tabla tal cual | 73% | 37% |
| 2: botella en la mano, diagonal del tajo, nube del aerosol, cabeza sin nariz | 74% | 42% |
| 3: huecos rellenos (partes pintadas, guantes, barras), lados de la persona | 91% | 52% |
| 4: colas más cortas, remolino, flechas que se vuelven máscara al 75% | 89% | 56% |

Lo que queda es sobre todo forma: un dibujo a mano no coincide trazo por trazo con el nuestro (el
aro de energía entre las manos de 16,8-17,6 es una burbuja; las líneas en "L" de la chaqueta de
9,1-9,6 son la solapa), y los destellos de 1-3 cuadros.
