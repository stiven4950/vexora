# video_34 · Baile en pareja (`baile_duo`)

Lectura de la referencia `glowing/video_34.mp4` (1073 fotogramas, 35,8 s), hecha con el criterio de
`docs/criterio_de_analisis.md`, y diagnóstico de nuestra versión.

Dos bailarines: **A**, de traje claro (person_0), y **B**, de saco rojo (person_1). Empiezan con
A a la izquierda; a los 13 s B cruza por delante y quedan al revés. Casi siempre hacen el mismo
paso.

## La intención del creador

Cada bailarín tiene **su color** todo el video: A cian o azul, B blanco o rosa. Con eso el creador
cuenta dos cosas:

1. **Cuando bailan igual, dibuja lo mismo en los dos**: aureolas, notas, corazones, rodillas,
   tobillos, el contorno del saco. Es la pareja como unidad.
2. **Cuando uno se aparta, solo ese se enciende** y el otro queda limpio, y se van turnando como
   en una conversación: B se abre el saco, A responde con la mano en la cabeza (corona), B da un
   paso al frente, A posa, B gira...

| Seg. | Qué pasa | Atención | Referencia |
| --- | --- | --- | --- |
| 0–2,5 | Caminan juntos hacia la cámara | La pareja que se presenta | **Aureolas y ojos encendidos en los dos**; línea en la solapa de A, corazón que sale de la mano de B |
| 3,0 | Patada | Las piernas | Casi nada (la aureola de A) |
| 3,5–4,5 | Mano al pecho, los dos | El pecho | Remolinos y trazos en el pecho de los dos |
| 5,5–6,5 | Brazos que marcan el ritmo | Las manos | **Notas musicales que salen de las manos de los dos** |
| 7,5 | Hombros | Los hombros | Rayos cortos sobre los hombros de los dos |
| 8,5–9,5 | Manos abiertas | Las manos | Destellos en las manos; corazón en A, rayo en el brazo de B |
| 10,0–10,8 | **B se abre el saco** (solo) | El saco de B | Contorno del saco con puntos, solo B |
| 11,0–11,7 | **A se lleva la mano a la cabeza** (respuesta) | La cabeza de A | Corona sobre A; rayo en el brazo de B |
| 12,0–14,0 | B da un paso al frente y cruza | La mano de B | Aro en la mano de B |
| 14,5–15,8 | B gira de espaldas; A posa | A | Rayos sobre el cuerpo de A y una luna sobre su cabeza |
| 16,2–16,7 | B de frente | La cabeza de B | Aureola y luna sobre B |
| 17,0–17,7 | **A se abre el saco** | El pecho de A | Estallido de luz en el pecho de A; aro en el pie de B |
| 18,0 | B gira | Los hombros | Garabatos en los hombros |
| 19,5–21,2 | Mismo paso | Las manos | **Corazones que salen de las manos de los dos** |
| 21,5–23,2 | Pasos marcados | Los pies | Chispas en el pie que pisa, los dos |
| 23,5–26,5 | Piernas abiertas, rodillas | Las rodillas | **Puntos en las rodillas de los dos** |
| 27,0–27,8 | Giro con los pies | Los pies | Aros en el piso alrededor del pie, los dos |
| 28,0–30,0 | De espaldas | La espalda | **Contorno del saco de los dos**; luego tramos en hombros y brazos |
| 31,0 | Giro | Los brazos | Arcos grandes que siguen los brazos, los dos |
| 32,0 | A mueve la mano (solo) | La mano de A | Aro en la mano de A |
| 33,0–34,8 | Mismo paso | Las piernas | **Línea por la pierna y banda en el tobillo, los dos** |
| 35+ | Final | — | Nada |

## Patrones

1. **Unísono → espejo.** Si los dos hacen el mismo paso, el mismo efecto en los dos, cada uno con
   su color.
2. **Solo → turno.** Si uno se aparta, solo ese; el otro queda limpio. Un gesto con significado
   del otro (mano a la cabeza) es su respuesta y sí se enciende.
3. **Un foco por persona.** Nunca dos efectos distintos en el mismo bailarín.
4. **Nada de contornos cerrados de brazos o piernas.** Líneas parciales: una línea por la pierna,
   la banda del tobillo, puntos en las rodillas. El contorno completo, solo del saco (de espaldas).
5. **La música sale de las manos** (notas y corazones), en ráfagas, no flotando todo el tiempo.
6. **Huecos.** Hay medios segundos sin nada entre momento y momento.

## Diagnóstico de nuestra versión anterior

| Problema | Causa |
| --- | --- |
| Piernas, brazos y torso dentro de una "salchicha" de neón (seg. 2, 5, 8, 17, 20) | La opción `contorno` (`body_glow` cerrado) era casi la única reacción de `spotlight` |
| Corazones y notas pequeños flotando sin motivo sobre las cabezas | `droplets` en `always`, con cualquier mano rápida y diminutos (tope de 11 px) |
| Casi siempre solo uno encendido, y al azar cuál | No había noción de pareja; cada persona sorteaba por su lado |
| La aureola de entrada solo en A | El evento `entrance` es de person_0 y `body_glow`/`adornment` dibujaban solo en él |
| Con un foco que nombra a la persona, `swoosh` no dibujaba nada y `body_glow` dibujaba en los dos | `focused()` y `_people()` no entendían un objetivo `person_N` sin articulación |
| `xray`, `wings`, rayos y demás siempre sobre person_0 | Usaban los puntos sin prefijo (la persona principal) |

## Qué se implementó

| Parte | Implementación |
| --- | --- |
| Unísono y solo | `analysis/duet.py`: compara las poses (articulaciones relativas a la cadera, en torsos) con ±0,2 s de tolerancia y en espejo; distancia suavizada < 0,2 = unísono (dos momentos al azar dan ~0,38). El resto es solo de quien más se mueve. Señal derivada `duet` en el brief |
| Espejo | `choreography.py` (`duet: true` en el catálogo): al unísono, el efecto elegido se copia a la pareja (su propio evento si hizo lo mismo; si no, una copia sin posición) como un efecto `_pareja` con su propio estado. Mientras dura, la pareja no enciende otro. Los efectos de todo el cuadro (discoteca, bola de espejos) no se copian |
| Turnos | En un solo, el otro no enciende lo que sale de puro movimiento (`spotlight`, pasos, `fast_swing`, frenesí); sus gestos sí |
| Un foco por persona | En pareja, el segundo foco de la línea de atención no enciende nada |
| Color por persona | `style.by_person`: el color N para person_N en todos los efectos; los puntos sin prefijo pasan a ser los de la persona del evento, así cualquier efecto se dibuja sobre quien corresponde |
| Catálogo | `baile_duo` rehecho: rodillas, tobillos con línea, onda por la pierna o el brazo, notas y corazones de las manos (disparados y grandes), líneas del pecho, saco, chaqueta, aureola, ojos, corona u ondas con la mano a la cabeza, torbellino o arcos al girar, chispas al pisar, fiesta en el frenesí |
