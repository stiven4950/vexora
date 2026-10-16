# video_18 · Maestro fuego (estilo Avatar)

Lectura de la referencia `glowing/video_18.mp4` (480 cuadros, 30 fps, 16 s, 720×1280 vertical) con
el criterio de `docs/criterio_de_analisis.md`. Un solista descalzo, en un estudio oscuro, hace una
rutina de artes marciales y acrobacia de piso: saltos, sentadillas, giros por el suelo, una
parada de manos. El animador lo convierte en un **maestro fuego** de *Avatar: la leyenda de Aang*.

## La intención del creador

- **El fuego sale de lo que hace el cuerpo:** cada golpe, salto o barrido deja una lengua de fuego
  con la forma de la trayectoria. Nunca hay fuego quieto pegado a las muñecas.
- **Fuego de anime:** formas planas con núcleo blanco-amarillo, borde naranja y lenguas
  definidas, no un brillo difuso.
- **La pantalla se calienta:** con el fuego grande, todo el cuadro se tiñe de naranja y vuelve a
  oscuro cuando se apaga.
- **El estado Avatar enmarca el video:** la flecha en la frente y los ojos encendidos al empezar
  y al terminar, y los ojos otra vez en los momentos de concentración.
- **Cierre:** una pared de fuego sube desde el piso hasta llenar el cuadro mientras él está en
  posición de meditación.

## Momento a momento

| Seg. | Qué hace | Atención y dirección | Referencia | Cómo lo haríamos |
| --- | --- | --- | --- | --- |
| 0,0-0,4 | Agachado, de lado | La cabeza | Flecha de Avatar en la frente y ojos blancos, halo naranja | `avatar_mark` en la entrada |
| 0,8 | Salta con los brazos abiertos | Los dos brazos, hacia afuera | Dos látigos de fuego en arco desde las manos; pantalla naranja | `fire_whip` en las dos manos + `grade` naranja |
| 1,2 | Brazos arriba, manos juntas | Las manos, hacia arriba | Dos lazos de fuego que suben desde las manos; arcos a los costados | `hand_fire` hacia arriba |
| 1,6 | Salto con las piernas abiertas | Todo el cuerpo | Remolinos enormes a los lados, núcleo blanco; pantalla naranja | `fire_whip` grande + `grade` |
| 2,0 | Cae en sentadilla, manos al piso | Las manos en el piso | Charco de fuego entre las manos | `floor_fire` |
| 2,4-2,8 | Sube las manos frente al pecho y la cara | Las manos, hacia arriba | Llamas en las dos manos que suben como velas | `hand_fire` / `candle` |
| 3,2 | Manos junto a la cabeza | La cabeza | **Calavera de fuego** con melena de llamas sobre la cara | `fire_skull` |
| 3,6-4,8 | Golpes y barridos de brazo, uno arriba | El brazo que golpea, en su trayectoria | Látigos de fuego que siguen el golpe; a los 4,8 una medialuna de fuego arriba | `fire_whip` |
| 5,2-5,6 | Estocada baja, la mano barre el piso | La mano en el piso, hacia el costado | Raya de fuego a ras del piso y chispas | `floor_fire` (barrido) |
| 6,0-7,6 | Agachado, manos juntas frente a la cara | Las manos | Una sola llama que sale de las manos y se achica de a poco; al final, ojos encendidos | `candle` |
| 8,0 | Baja al piso girando el brazo | La mano | Un aro de fuego alrededor del brazo | `fire_ring` |
| 8,4-8,8 | En el piso, boca abajo | La cara | Brasas sueltas; ojos y rasgos encendidos | `avatar_mark` (solo ojos) |
| 9,2-10,8 | Trabajo de piso: barre con la mano y el pie | La extremidad que barre, a ras del piso | Rayas largas de fuego sobre el piso | `floor_fire` (barrido) |
| 11,2-11,6 | Cuatro apoyos de frente a la cámara | Todo el cuerpo | Llamas que trepan por brazos y piernas y alas de fuego arriba: el cuerpo arde | `body_blaze` + `grade` |
| 12,0-13,6 | Parada de manos y bajada | Las manos en el piso, los pies arriba | Llamas bajo las manos, estallidos arriba, brasas que caen | `floor_fire`, brasas |
| 14,0 | Cae con los brazos abiertos | Los dos brazos | Látigos de fuego a los lados | `fire_whip` |
| 14,4-16,0 | Manos juntas en el pecho, rodilla al piso | Meditación | Flecha en la frente, ojos blancos; una pared de fuego sube desde el piso hasta llenar el cuadro | `fire_wall` + `avatar_mark` |

## Patrones

1. **Trayectoria → látigo de fuego** (P2): la forma del fuego es la del movimiento que lo lanzó.
2. **Manos juntas → una llama** (P4): concentrar la energía; se achica si las manos se quedan
   quietas.
3. **Mano o pie en el piso → fuego en el piso**: charco si se apoya, raya si barre.
4. **Cuerpo entero en tensión → el cuerpo arde**.
5. **Fuego grande → pantalla naranja** (un tinte de todo el cuadro).
6. **Estado Avatar al principio y al final**.
7. **Entre golpe y golpe, brasas** que flotan.

## Los dos presets de avatar

`avatar_fire` (fuego continuo en las muñecas, sin reaccionar a nada) no se parece a esta
referencia, y `avatar_storm` (rayos en los golpes, chispas, grietas) reacciona a eventos pero es
otro elemento. Se unifican en un solo estilo de coreografía, **Avatar** (`configs/catalogs/avatar.yaml`):
el fuego de esta lectura como base, y los rayos de `avatar_storm` como **rayo de fuego** (como el
de los maestros fuego de la serie) en los golpes de señalar y en algunos golpes rápidos.

## Primera versión y lo que falta

Render: `historial/video_18/2026-10-16_avatar_v1.mp4`. Lo nuevo en el motor está en
`engine/firebend.py` (fuego plano en tres capas con resplandor radial alrededor) y el catálogo en
`configs/catalogs/avatar.yaml`. Para que los golpes y saltos no queden sin fuego, el catálogo
tiene `priority`: esas acciones se reparten primero los dos focos (antes, el fuego del piso de cada
pisada los tapaba).

Diferencias que quedan con la referencia:

- Los látigos siguen la trayectoria real de la mano (doblada): salen grandes pero bastante rectos;
  el animador los dibuja como medialunas muy curvas.
- La pantalla naranja aparece con los látigos, saltos y el cuerpo en llamas, pero menos que en la
  referencia, que la tiñe casi siempre que hay fuego.
- La flecha de Avatar del inicio sale chica (la cara es chica en el plano) y en el cierre la tapa
  a veces la llama de las manos.
