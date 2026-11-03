# video_55 · prueba de outfits frente al espejo (modelaje por capas)

Referencia `glowing/data/glowing/video_55.mp4`, original `glowing/data/original/video_55.mp4`.
6,6 s, 198 cuadros, 30 fps, 720×1280. Leído el 2026-11-02 con hojas cada 0,27 s y la imagen de "solo
efecto" (referencia menos original). Mismo género que video_46 (docs/referencias/video_46.md): el
foco es la ropa. Lo que este video agrega está marcado como **nuevo**.

## Qué tipo de video es

Una persona frente al espejo, casi quieta, que posa y va cambiando de ropa a saltos: camiseta y short;
un salto la viste con sudadera (1,9 s); después suma pantalón cargo, chaqueta bomber, auriculares y una
mochila que levanta, cuelga y balancea. Hay 9 cortes (66, 72, 97, 121, 135, 151, 166, 183), pero **casi
todos son la misma ropa con una capa más**: el color no cambia con ellos.

## Momentos

| Seg. | Persona | Referencia | Patrón |
| --- | --- | --- | --- |
| 0,0-1,8 | Camiseta negra y short, brazos cruzados, poses mínimas | Casi nada: destellos rojos cortos que recorren el borde del hombro o el pecho | **Nuevo**: con la persona quieta, un brillo que recorre un borde de la prenda (no se delinea todo) |
| 1,8-1,9 | Salta y la ropa cambia en el aire (la sudadera aparece con estela de movimiento) | Contorno rojo en zigzag sobre los hombros con separación de color (rojo, verde y azul desfasados) | **Nuevo**: el salto de cambio se anuncia |
| 1,9-2,1 | Cae ya con sudadera | Un relleno blanco brillante **barre la prenda nueva** de un lado al otro | **Nuevo**: revelado de la prenda (paint reveal) en el cambio de outfit |
| 2,1-2,7 | Sudadera, luego pantalón | La prenda entera teñida de verde, contorno blanco y un borde **iridiscente** (separación de color); los zapatos en arcoíris con reflejos de colores en el piso | **Nuevo**: prenda completa holográfica al estrenarla; calzado iridiscente |
| 2,4-3,5 | Pantalón cargo, chaqueta bomber, auriculares | El relleno se apaga y quedan los bordes delanteros de la chaqueta y los bolsillos; una **onda en zigzag** tipo electrocardiograma recorre el pantalón a la altura de la cadera | Como video_46 (bordes de la prenda, patrón en zigzag); **nuevo**: la onda animada en una banda |
| 3,5-4,4 | Levanta la mochila | Mochila delineada en rosa, con relleno suave y separación de color; costuras verticales del pantalón en amarillo verdoso; chispitas | Accesorio delineado (como el bolso de video_46), costuras largas |
| 4,4-5,0 | Brazo extendido hacia el espejo | **Burbujas de luz** (anillos rosas con separación de color) que flotan; una en la mano extendida; tramos del brazo | **Nuevo**: anillos flotantes, uno en la mano protagonista |
| 5,3 | De frente, manos en los bolsillos | El **logo de la sudadera** se vuelve un símbolo de luz | **Nuevo**: trazar el logo o estampado de la prenda |
| 5,6 | Balancea la mochila | Un barrido de luz lila enorme sigue a la mochila | Estela del objeto rápido (como la gorra de video_33) |
| 5,9 | Mochila al hombro | La correa de la mochila sobre el hombro | Accesorio delineado, parcial |
| 6,1-6,6 | Final, quieta | **Luz de prisma**: franjas diagonales de arcoíris sobre la tela de la chaqueta y el pantalón, y un resplandor cálido en el pantalón | **Nuevo**: cierre con luz de prisma sobre la ropa |

## Patrones (combinados con video_46)

0. **Zonas pintadas y destellos que recorren la prenda** (observación del usuario, 2026-11-02): dentro de
   un mismo outfit se pintan ciertas zonas de la ropa (la manga, el frente de la chaqueta, una pierna
   del pantalón, la mochila) con un tinte de luz, y por encima pasan brillos que se deslizan por la tela
   como un reflejo, de una zona a otra. Da la ilusión de un material brillante sin cambiar de outfit; es
   el recurso principal del video, más que los contornos. Las zonas salen de la prenda segmentada
   partida por la pose (torso, mangas, piernas) y de los accesorios.
1. **El color va con el outfit, no con el corte.** En video_46 cada corte era un outfit nuevo; aquí 9
   cortes y tres colores (rojo, verde, verde con acentos rosa y amarillo). Hay que medir si la ropa
   cambió (color y forma de la prenda antes y después del corte) y abrir capítulo solo entonces.
2. **Ciclo de un outfit nuevo**: se anuncia (zigzag en los hombros) → se revela (barrido blanco) → se
   estrena entera (relleno holográfico) → quedan los trazos clave (bordes, costuras, patrón). En video_46
   el outfit entraba directamente en la última fase.
3. **Capas que se suman sin cambiar de color**: la chaqueta, el pantalón y la mochila que aparecen se
   delinean con el color del capítulo (la mochila con un acento).
4. **Estilo holográfico**: separación de color en los contornos (rojo, verde y azul desfasados unos
   píxeles) y arcoíris en el calzado.
5. **Con poco movimiento, poco dibujo**: un destello que recorre un borde.
6. **Lo que se mueve se atiende**: la mano extendida recibe un anillo; la mochila balanceada, una estela.
7. **Estampados**: el logo de la prenda se traza.
8. **Cierre propio**: luz de prisma sobre la ropa (en vez de las estrellas de siempre).

## Lo que ya tenemos (catálogo `desfile`)

Bordes de la prenda, costuras, calzado y accesorios delineados (`analysis/garment.py`,
`engine/garment_fx.py`), un color por capítulo, piezas de cabeza, cortes deslizantes. Sobre el original
de este video, `desfile` ya delinea los bordes delanteros de la bomber y el calzado (el usuario lo dio
por bueno).

## Lo que falta, por prioridad

0. ✅ **Zonas pintadas con destellos** (2026-11-02): `analysis/garment.py` parte la prenda con la pose
   (torso, mangas, piernas, bolso, calzado de cada pie; descarta lo que no toca a la persona, como el
   reflejo del espejo) y `garment_zones` (acción `outfit_zone` de `desfile`) tiñe una zona por turno
   (~0,9 s, con fundido), la cruza con un brillo diagonal y pone destellos donde toca el borde. Con
   cortes muy seguidos (este video), cada toma vuelve a empezar por el torso: lo arregla el punto 1.
1. ✅ **Capítulo solo con cambio de outfit** (2026-11-03): `garment.outfit_changes` busca picos del cambio
   de color de la prenda (no los cortes) y el catálogo `desfile` los usa para sus outfits y colores
   (`MotionBrief.outfits`, guardado en `analysis/outfits.json`). video_55 da un solo cambio (57, el de la
   referencia); video_46, sus cuatro outfits. Los trazos se siguen eligiendo por toma.
2. ✅ **Revelado y estreno** (2026-11-03): `garment_reveal` (acción `outfit_reveal`): barrido diagonal de
   luz sobre la ropa (0,3 s), prenda entera teñida con su silueta (0,4 s) y fundido (0,35 s); no en el
   outfit del comienzo, y a veces no (opción `nada`).
3. ✅ **Estilo holográfico** (2026-11-03): en ~35% de los outfits (o fijo con `style.variants.holo`),
   `garment_lines` pone a cada línea una copia roja y otra azul corridas y pinta el calzado en arcoíris.
4. ✅ **Onda en banda** (2026-11-03): `garment_ecg` (acción `outfit_wave`, ~45% de los outfits): hebras con
   picos de electrocardiograma que cruzan el pantalón a la altura de la cadera, recortadas a la prenda.
5. **Anillos flotantes** con separación de color, uno en la mano que más se mueve.
6. **Destello que recorre un borde** cuando la persona está quieta.
7. **Logo o estampado**: una mancha de alto contraste dentro de la prenda, trazada.
8. **Estela del accesorio** que se mueve rápido (como `prop_swoosh`, con el bolso o la mochila de la
   segmentación).
9. **Cierre de prisma**: franjas de arcoíris que se deslizan sobre la prenda.
