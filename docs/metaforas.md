# Metáforas con historia

Efectos que no decoran: cuentan una pequeña aventura sobre el cuerpo, con principio, conflicto y
final, para atrapar la mirada (idea del usuario a partir de video_35). Este documento es la guía
para elegirlas, tanto para el coreógrafo como para el director con IA (`docs/plan_director_ia.md`).

## Cómo se arma una

1. **El escenario es el cuerpo.** Un brazo extendido es una plataforma o un puente; la cabeza, un
   planeta o una cima; las manos, trampas, nidos o lanzadores; el pecho, un tablero.
2. **El gesto da el conflicto.** La otra mano que se acerca persigue; un giro centrifuga; un
   pisotón derrumba; brazos que se cruzan cierran el paso.
3. **El final se conecta con lo que sigue.** Lo que se desintegra deja chispas que pasan al próximo
   efecto; lo que choca suelta energía; lo que se carga queda lleno para el siguiente movimiento.

## Las de video_35 (implementadas)

| Metáfora | Disparador | Historia |
| --- | --- | --- |
| Muñequito de palitos (`stick_man`) | Señalar con el brazo extendido | Aparece en la mano, camina sobre el brazo, cae, la otra mano lo ataja, da una vuelta y lo aplasta: chispas |
| Ovni (`ufo`) | Manos sobre la cabeza | Nace entre las manos, orbita la cabeza en perspectiva, se sale de control, deja caer algo en el pecho y persigue las manos |
| Globo de agua (`water_balloon`) | Golpe o patada muy rápida | Se estira con la velocidad, se aplasta al frenar, tiembla y revienta en gotas: el lanzamiento de béisbol |
| Serpiente (`snake`) | Brazo protagonista | Recorre los brazos de mano a mano, se enrosca en la muñeca y sale disparada como un rayo |
| Batería (`battery`) | Brazos que se abren | Se carga en el pecho hasta el "100%" |

## Las que propuso Gemini al leer video_35 completo (implementadas)

Gemini (Argon) recibió el video entero con el prompt de animador y propuso estas cuatro. Su guion
está en `configs/pruebas/video_35_gemini.yaml`. Escuchar la letra de la canción le dio dos de ellas.

| Metáfora | Opción del catálogo | Historia |
| --- | --- | --- |
| Chispa atrapada (`spark_trap`) | `spotlight: chispa` | Salta de la gorra a la mano levantada, intenta escapar, el puño la atrapa dos veces y se parte en dos aros que corren a las muñecas |
| Soga del tiempo (`time_rope`) | `spotlight: cuerda` | Un ancla se clava detrás de él; al jalar, la soga se tensa, vibra y marca "<<"; al final se enrolla en las manos como una bola de energía |
| Traje de luz (`supersuit`) | `spotlight: traje` | Con la letra "I don't need no supersuit": dos cierres suben dibujando una armadura, el emblema brilla y las placas caen como gotas |
| Planeador (`glider`) | `arms_open: planeador` | Alas entre las muñecas y la cintura, ondas de la sirena a los costados y, al final, un rayo de punta a punta de los brazos |

## Propuestas para otros videos

| Metáfora | Cuándo encaja | Historia |
| --- | --- | --- |
| Abeja o mosca molesta | Manos que espantan, cabeza que esquiva | Zumba alrededor de la cabeza, la mano la espanta, vuelve, la atrapa con un aplauso: estrellitas |
| Bola de energía (estilo kamehameha) | Manos juntas que retroceden y empujan | Crece entre las manos durante la carga y sale disparada al empujar |
| Pelota de básquet | Manos que botan algo, brazo que lanza | Bota entre la mano y el piso, gira en un dedo y entra en un aro dibujado |
| Cohete | Salto o brazos arriba | Despega desde los pies con humo, sube por el cuerpo y explota en fuegos artificiales sobre la cabeza |
| Gato que juega | Mano que se mueve despacio | Un gatito persigue la mano como a un láser y salta a atraparla |
| Rayo que se transfiere | Choque de manos con la pareja | Pasa de una persona a la otra por las manos y recorre su cuerpo |
| Pájaro | Brazos que se abren lento | Se posa en el brazo extendido, picotea, sale volando al cerrarlo |
| Mancha de tinta | Pisotón | Salpica bajo el pie y sube por la pierna como pintura que trepa |
| Corazón con alas | Corazón con las manos | Nace entre las manos, aletea, sale volando y se pierde en el aire |
| Imán | Mano que atrae | Objetos pequeños (estrellas, notas) se pegan a la mano y salen disparados al abrirla |
| Burbuja | Persona quieta | Una burbuja la envuelve, tiembla con los movimientos pequeños y revienta al moverse fuerte |
| Planeta en órbita | Giro sobre sí mismo | Un planetita orbita la cintura más rápido mientras gira, y sale despedido al parar |

## Cómo elegirla con IA

El director con IA (nivel profundo de `docs/plan_director_ia.md`) recibe por cada momento clave
una tira de fotogramas y los datos del movimiento. Para estas metáforas se le pide que actúe como
un animador profesional: describir la intención del gesto (huye, atrapa, carga, presume), elegir
una metáfora de esta lista o proponer una nueva con la misma estructura (escenario, conflicto,
final) y decir en qué momento empieza y termina. Hoy el coreógrafo solo las dispara por el gesto
(`_baile_compartido.yaml`); la elección por intención llega con ese nivel.
