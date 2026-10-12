# Criterio de análisis: cómo leer un video antes de animarlo

Este documento recoge la forma de pensar con la que se analizan las referencias (los videos
"glowing" hechos a mano por un creador). Es la regla a seguir **antes** de proponer efectos para
un video nuevo, y el texto que se le da al director con IA (`--director openai`) para que razone
igual.

La idea central: un creador no decora el video; **lee lo que hace la persona** (a dónde va su
atención, hacia dónde se mueve, qué gesto hace y qué significa) y **dibuja eso**. Cada video es
distinto: estas reglas no dicen qué efecto poner, dicen cómo decidirlo.

## 1. Principios

### P1. Un protagonista a la vez (y a veces dos)

En cada momento hay una cosa que manda: una parte del cuerpo, un objeto, la cara. El efecto va
**ahí** y en ningún otro lado.

- **Protagonista = lo que se mueve más de lo normal para esa parte**, no lo que más se mueve en
  absoluto (los brazos siempre recorren más que la cabeza). Ver `spotlight` en
  `analysis/events.py`.
- **Un objeto en las manos le gana al cuerpo**: si las manos están en la gorra, la gorra es la
  protagonista.
- **Con el cuerpo quieto, la atención pasa a la mirada y la expresión** (video_33, 19 s).
- **A veces hay dos focos** (video_33, 26 s: un pie que pinta el piso y las manos que lanzan la
  gorra). Hay que atender los dos, y no más de dos.
- **Nada compite con el protagonista.** Un segundo efecto encendido en otra zona, o encima del
  mismo, arruina la escena. Si dos efectos chocan, uno cede. Implementado: línea de atención
  (`analysis/attention.py`) y `engine/focus.py`.

### P2. Seguir la dirección del movimiento

El efecto viaja hacia donde va el movimiento, a la misma velocidad.

- Anillos que suben por el brazo hasta el hombro y, cuando el movimiento cambia de lado, hacen
  el mismo juego en el otro brazo (15 s).
- Contornos que suben por las piernas de abajo hacia arriba como una onda (24 s).
- Una mancha que sigue al pie y gira cuando el pie gira (25-26 s).
- Un objeto lanzado lleva una estela en la dirección del lanzamiento (27 s).

Pregunta obligada en cada momento: **¿de dónde viene y a dónde va la energía?**

### P3. La energía se transfiere

La atención no salta: pasa de una parte a otra y el dibujo la acompaña. La mano gana
protagonismo y se delinea; luego la animación **se transfiere** a los pectorales; al pasar las
manos por delante, vuelven a mandar las manos; después la energía recorre los bordes del cuerpo
(13-15 s). El cambio de foco se dibuja como un traspaso (trazo que avanza, anillo que viaja, una
línea que pasa de una zona a la siguiente), no como un corte.

### P4. Los gestos tienen significado: dibujar la metáfora

Un gesto reconocible se convierte en su imagen. Ejemplos de video_33 (ver el diccionario en la
sección 3):

- Llevar la mano a la cara y "arrancar" algo → aparece algo en la mano (bola de energía).
- Amagar un lanzamiento → eso merece atención: proyectil, explosión de partículas, rayo.
- Pasar la mano por el cuello ("ya valió") → ojos en X y luego gafas.
- Besar → labios; al apartar la mano, el beso viaja hasta los dedos.
- Pisar fuerte → un globo que revienta, chispas, aire.

El efecto aparece **con el gesto** (un poco antes, si el gesto se anuncia) y dura lo que dura.

### P5. Los objetos reales son protagonistas

Un objeto que la persona usa (gorra, espada, bastón) se detecta, se sigue y se dibuja con su
contorno real. Los efectos se orientan con **su** eje (anillos, orejas, resortes). Si el objeto
se mueve rápido, a veces es mejor una **estela o mancha grande** que lo sigue que su contorno
(26-27 s). Puesto o guardado, deja de ser protagonista.

### P6. Coherencia anatómica y de orientación

El dibujo tiene que tener sentido sobre el cuerpo tal como se ve:

- **De frente**: abdominales, pectorales, collar.
- **De espaldas**: músculos de la espalda o una figura de relleno (símbolo radiactivo, sol,
  emblema), nunca abdominales (18-19 s).
- **Partes tapadas** no se dibujan.
- La escala sale del cuerpo (torso, distancia entre orejas), no de la pantalla.

### P7. Menos es más

- **Trazos parciales, no cajas completas**: unas líneas de pectoral, un tramo de contorno de
  pierna, no la figura entera (14 s, 24 s).
- **Un efecto por zona y por momento.** Implementado: opciones `exclusive` y tope de dos focos en el
  coreógrafo.
- **El efecto se apaga cuando el foco se va**: la gorra puesta deja de dibujarse; la cara deja
  de brillar cuando la mano se aparta.

### P8. Color por capítulo, y que contraste

- El color **solo cambia cuando cambia el foco**. Todo lo que se enciende en ese capítulo
  comparte color.
- El color tiene que **contrastar con la piel** de la persona (ver `director/palette.py`).

### P9. Ritmo y variedad

- Los efectos tienen **anticipación** (aparecen un poco antes del gesto), duración y salida.
- No siempre el mismo efecto para la misma acción: se sortea con pesos, sin repetirlo seguido.
- Hay momentos sin efecto: el vacío hace que el siguiente se note.
- Pero tampoco escasez: si en un tramo no pasa nada, se buscan contornos que recorran el
  cuerpo (arriba, luego abajo) hasta que algo tome el protagonismo (23 s).

### P10. Cierre

Aproximadamente 1 s antes del final, todo lo dibujado se **disipa en partículas diminutas**
(estrellas, chispas) en el lugar donde estaba (sombrero y cinturón se vuelven estrellas, 29 s),
hasta que queda la persona sola.

### P11. Estilo de línea

Línea de neón con núcleo blanco fino (0,5% del ancho del cuadro, 90% de opacidad) y el color en
el halo. Las partes del cuerpo encendidas van en dos pasadas: tinte que conserva la luz de la piel
y la línea blanca encima.

## 2. Procedimiento para una referencia nueva

1. **Hojas de contacto**: original y referencia cada 0,25-0,3 s, y zoom en los momentos con
   dibujos.
2. **Tabla por momento** (una fila cada vez que algo cambia):

   | Seg. | Qué hace la persona | Dónde está la atención | Hacia dónde va el movimiento | Gesto y significado | Qué dibuja la referencia | Cómo lo haríamos | Qué hay que detectar |
   | --- | --- | --- | --- | --- | --- | --- | --- |

3. **Patrones**: qué se repite (el foco salta de A a B y el dibujo lo acompaña; tal gesto
   siempre da tal imagen). Cada patrón es una regla de catálogo o un evento nuevo.
4. **Qué falta**:
   - un evento que el análisis no ve (un gesto, un objeto, un foco);
   - una primitiva que el motor no dibuja;
   - una regla de coreografía (prioridad, cesión, transferencia).
5. **Validar sobre el original contra la referencia**, cuadro a cuadro, con recortes del mismo
   lugar. Medir, no suponer (grosores, tiempos, distancias).
6. **Generalizar**: el resultado no es copiar la referencia, es un catálogo que haga cosas de ese
   estilo en otros videos, con variedad.

## 3. Diccionario de gestos

Qué detectar y qué imágenes caben. La columna de efecto da opciones; se sortea entre ellas.

| Gesto | Cómo se detecta | Imágenes posibles | Estado |
| --- | --- | --- | --- |
| Mano a la cara (beso, tocar) | Puntas de dedos junto a la cara (`face_touch`) | Labios, pestañas, cara teñida; al soltar, el beso viaja a los dedos | ✅ |
| Arrancar algo de la cara | Mano cerca de la cara que se aleja rápido y cerrada | Bola de energía en la mano | ❌ |
| Amago de lanzamiento | Brazo atrás (carga) y extensión rápida hacia afuera | Proyectil, rayo, explosión de partículas en la dirección | ✅ (`throw`, `throw_fx`) |
| Corte de cuello ("ya valió") | Mano plana que cruza el cuello de lado a lado | Ojos en X, luego gafas | ✅ (`neck_slash`) |
| Pisotón o pie que se levanta y baja | Tobillo que baja rápido y se detiene | Globo que revienta, chispas, aire | ✅ (`stomp`, `pop_fx`) |
| Pie que arrastra o barre el piso | Tobillo bajo que se desplaza | Mancha de agua o pintura que lo sigue y gira | ✅ (`foot_paint`) |
| Flexionar el brazo | Codo alto, antebrazo vertical | Brazo musculoso | ✅ (`biceps`) |
| Pasar un objeto de mano a mano | `prop_transfer` | Resorte, doble contorno | ✅ |
| Girar el objeto en las manos | `prop_spin` | Anillos que lo recorren; al acabar, orejas o corazón | ✅ |
| Ponerse el objeto | `prop_worn` | Caricatura de la cara con el objeto | ✅ |
| Lanzar el objeto | Objeto que sale rápido de la mano | Estela o mancha grande que lo sigue | ✅ (`prop_swoosh`) |
| Darse la vuelta | Hombros invertidos (izquierdo a la derecha) | Espalda: músculos o figura de relleno | ✅ (`facing`, `badge`) |
| Cuerpo quieto, cara expresiva | Poco movimiento corporal, cambios en la boca o los ojos | Exagerar la expresión (sudor, "!!", "?", enojo, ojos de corazón) | ✅ (`face_toon` expresiones) |
| Manos al cinturón o a la cadera | Muñecas a la altura de la cadera | Cinturón de metal con brillo que se mueve | ✅ en parte (`belt`, sin detectar el gesto) |
| Corazón con las manos | Muñecas juntas frente al pecho | Corazón que late y sube | ✅ (`heart_hands`) |
| Señalar | Brazo extendido con el índice estirado | Rayo o flecha con impacto | ✅ (`point`) |
| Brazos arriba | Muñecas sobre la cabeza | Confeti, fuegos artificiales | ✅ (`arms_up`) |
| Brazos en cruz | Muñecas separadas a la altura de los hombros | Alas | ✅ (`arms_open`) |
| Mano en el oído | Dedos junto a la oreja | Ondas de sonido | ✅ (`hand_ear`) |
| Mano en los ojos | Dedos sobre los ojos | Antifaz o venda | ✅ (`cover_eyes`) |
| Giro sobre sí mismo | Frente → espaldas → frente en menos de 1 s | Torbellino alrededor del cuerpo | ✅ (`spin_body`) |
| Baile intenso | Todo el cuerpo muy por encima de lo habitual | Discoteca, ecualizador | ✅ (`frenzy`) |
| Pausa | `still`, `lull` | Accesorios (collar, estrellas en el pecho, sombrero) | ✅ |
| Fin del video | Último segundo | Todo se disipa en estrellas diminutas | ✅ (`closing_stars`) |

## 4. Ejemplo trabajado: video_33, segundos 9-30

Leído sobre la referencia (`glowing/video_33.mp4`), con lo que hay que hacer en el motor.

| Seg. | Persona | Atención y dirección | Referencia | Falta |
| --- | --- | --- | --- | --- |
| 9,0-10,1 | Aparta la mano de la cara y flexiona el brazo derecho arriba | Brazo derecho; la energía sale de la cara hacia la mano | Brazo verde musculoso | Hoy el beso se apaga; la energía debería pasar a la mano |
| 10,3-10,6 | Mano arriba, como si sostuviera algo; amaga lanzarlo | La mano; va a lanzar | Bola de luz blanca en la mano, mancha verde que sale | Evento de amago de lanzamiento; proyectil, rayo o explosión |
| 10,9-11,4 | La mano baja al pecho | Cuello y pecho | Cadena con dije al cuello | Cadenas (de vez en cuando) |
| 11,9-13,0 | Mano por el cuello y luego quieto | Cara | Ojos en X, después gafas, cara teñida | Gesto de corte de cuello y secuencia X → gafas |
| 13,3-13,8 | Mano derecha junto a la cabeza, con más movimiento | Mano derecha | Mano delineada (dedos) | Foco en la mano (no en el brazo entero) |
| 14,1-14,9 | Brazo derecho y luego las manos frente al pecho | De la mano a los pectorales | Brazo amarillo; después unas líneas de pectoral y una cadena | Transferencia mano → pecho; pectorales parciales |
| 15,1-15,4 | Manos que suben y bajan | Mano izquierda → hombro → mano derecha | Aros que viajan por el brazo | Anillos sobre la cadena del brazo, en la dirección del movimiento |
| 15,7-17,3 | Se quita la gorra y juega con ella | La gorra | Contorno de la gorra; una mancha grande que la sigue | Mancha que sigue al objeto rápido; nada más encendido |
| 17,8-19,9 | Se da la vuelta | Espalda y gorra en las manos | Espalda con símbolo radiactivo | Detectar espalda: nada de abdominales; figura de relleno |
| 19,1 | Cuerpo quieto, mira a cámara | La mirada | Ojos y cara que brillan | Foco en la expresión |
| 20,2-20,5 | Se pone la gorra | La gorra | Contorno de la gorra puesta | ✅ |
| 20,7-22,9 | Manos al pecho | Pecho y brazos | Collar, estrellas en el pecho | ✅ en parte |
| 23,1-23,7 | Piernas abiertas, poco movimiento | Nadie; recorrer el cuerpo | Contorno de pantalón y luego de los pies | Contornos de relleno que suben y bajan |
| 23,9-24,7 | Mueve las piernas | Piernas; de abajo hacia arriba | Tramos de contorno que suben por las piernas | Onda de contornos parciales en la dirección del movimiento |
| 25,0-25,8 | Pierna extendida que vuelve al centro | Pie derecho | Mancha en el piso bajo el pie que gira con él | Mancha de pintura del pie |
| 26,1-27,4 | Pie que pinta y manos que lanzan la gorra | Dos focos: pie y gorra | Mancha serpenteante entre las piernas, estela grande de la gorra | Dos focos a la vez; estela del objeto lanzado |
| 28,2-29,0 | Pisa, manos al cinturón | Cuerpo entero | Sombrero, ojos de punto, cinturón de metal con brillo, globo que revienta bajo el pie | Sombreros variados, cinturón con brillo, pisotón con chispas |
| 29,3-29,8 | Final | Cierre | Sombrero y cinturón se vuelven estrellas y se apagan | Disolución final en partículas |

Errores de nuestra versión que esta lectura corrige:

- **Interferencia**: se encendían dos cosas a la vez (gorra y brazo, accesorio sobre la
  caricatura).
- **Abdominales de espaldas** (18 s).
- **Foco único**: no se atendían dos focos simultáneos (26 s).
- **Cajas completas**: pectorales y piernas se dibujaban enteros donde la referencia usa unas
  pocas líneas.
