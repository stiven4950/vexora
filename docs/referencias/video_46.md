# video_46 · desfile con cambios de outfit (modelaje)

Referencia `glowing/data/glowing/video_46.mp4`, original `glowing/data/original/video_46.mp4`.
5,2 s, 156 cuadros, 30 fps, 720×1280. Leído el 2026-11-02 con hojas cada 0,2 s, recortes de cada
capítulo y la imagen de "solo efecto" (referencia menos original).

## Qué tipo de video es

No es baile: una modelo camina hacia la cámara, de perfil a tres cuartos, sin gestos ni movimientos
bruscos. Cada pocos segundos hay un **corte de outfit** (mismo lugar, ropa distinta). El creador no
dibuja lo que la persona hace: **delinea la ropa**. Cada outfit es un capítulo con su color y sus
propios trazos, que dependen de la prenda (costuras, bordes, franjas, accesorios). Encima pone una
pieza en la cabeza que define el personaje del outfit (cachos, aro, orejas, gafas).

Es una categoría nueva: **desfile / modelaje**. Varias de sus técnicas sirven también en baile
(delinear prendas en una pausa, anillos en rodillas y codos) y en cara neón (gafas, orejas, cachos).

## Capítulos

Cortes medidos en el original (salto de imagen): 26-27, 59, 88-90, 120-122 y 153 (vuelve al primer
outfit: el video es un bucle). Los de 2-3 cuadros son transiciones deslizantes: el clip nuevo entra
de lado y su dibujo ya está puesto sobre él (con el color viejo un cuadro; al siguiente, el nuevo).

| Seg. | Outfit | Color | Cabeza | Prenda | Calzado y accesorios |
| --- | --- | --- | --- | --- | --- |
| 0,0-0,9 | Gorra, sudadera gris ancha, falda cargo larga, botas | verde | Barra horizontal sobre los ojos, bajo la visera | Costura curva del hombro; dos líneas largas por los bordes de los bolsillos de la falda; el lazo en "U" de una correa colgante | Suela de cada bota |
| 0,9-1,97 | Abrigo largo, corbata, minifalda, botas de plataforma | rojo | Cachos de diablo curvos y el contorno de las gafas de sol reales | Bordes delanteros del abrigo de la solapa al ruedo (líneas largas, continuas); borde del abrigo contra la pierna; puños | Bota de plataforma delineada completa; línea en la caña |
| 1,97-2,95 | Boina, chaleco y saco marrón, falda, bolso | cian | Aro plano sobre la cabeza; acentos finos en la cara | Arcos en los hombros (como paréntesis), anillo en codo y antebrazo | Anillos alrededor de las rodillas con líneas por la pierna; tramos del contorno del bolso |
| 2,95-4,03 | Chaqueta plateada acolchada corta, pantalón acampanado, bolso acolchado | lila (acento azul) | Orejas de gato con oreja interior y gafas | Puntos en los picos del acolchado; luego una línea en zigzag tipo electrocardiograma sobre el pecho y la línea del cierre | Bolso con su acolchado dibujado (burbujas, flores); las aberturas del ruedo del pantalón |
| 4,03-5,1 | Chaqueta roja y negra corta con franjas blancas, pantalón negro, bolso | naranja | Lucecitas sobre el pelo (como guirnalda) | Las franjas blancas de la chaqueta (banda del pecho, ruedo a la cintura) y el ribete de las mangas | Tramos del bolso (asas, borde), punteras de los zapatos, tramos cortos en las rodillas |

## Cómo dibuja

- **Trazos de la prenda real, no del cuerpo**: costuras, bordes de solapa, franjas, cierres, ruedos,
  aberturas, la frontera entre prenda y piel (borde del abrigo contra la pierna, cintura del crop
  top) y entre prenda y calzado (caña de la bota).
- **Parciales** (P7): unas pocas líneas largas por outfit, nunca la silueta entera. En el rojo, dos
  líneas casi de cuerpo entero; en el resto, tramos.
- **Calcado cuadro a cuadro**: las líneas siguen la tela al caminar (rotoscopia).
- **Calzado y bolso**: casi siempre delineados (el calzado completo en el rojo; la suela en los
  demás).
- **Pieza de cabeza por outfit**: barra de ojos, cachos más gafas, aro, orejas más gafas, lucecitas.
- **Textura**: si la prenda tiene un patrón fuerte (acolchado en zigzag), se dibuja el patrón (puntos
  en sus picos, la línea en zigzag), no el borde.
- **Articulaciones** en un outfit (cian): arcos en hombros, anillos en codos y rodillas.
- **Entrada**: completo en el corte, sin trazarse.
- **Salida**: a veces se parte en guiones en los últimos ~6 cuadros (rojo, 52-58); otras sigue hasta
  el corte.
- **Color**: uno por outfit, saturado, con núcleo blanco; en lila, un segundo tono azul en las orejas.
- Línea de neón de grosor parecido al del resto de vfxglow (núcleo blanco fino, halo del color).

## Lo que ya tenemos

| Necesidad | En Vexora |
| --- | --- |
| Capítulos por corte, color por capítulo | `cut_frames`, `chapters`, `color_per_effect` |
| Cachos, gafas, aro, orejas de gato | `red_horns`/`horns`, `eyewear` (frames, visor), `head_halo`, orejas de `eyes_feline` |
| Anillos en articulaciones | anillos de brazo y rodilla del baile (`limb`, `arm_fx`) |
| Salida en guiones | `dissolve.melt` (deja tramos punteados) |
| Accesorios reales (gafas de sol) | `analysis/accessories.py` (VLM) |
| Ropa, piel, pelo y "otros" por píxel | `analysis/regions.py` (segmentador multiclase) |

## Lo que falta

1. **Trazos de la prenda** (lo central). Prueba del 2026-11-02 sobre cuadros 12, 40, 105 y 135:
   - la clase "otros" del segmentador aísla calzado, gorra y bolsos (el bolso negro sale casi
     perfecto; el plateado acolchado no);
   - las fronteras entre clases dan justo varios trazos de la referencia (prenda/piel, prenda/calzado,
     silueta contra el fondo), limpios pero a 256 px;
   - los bordes internos (Canny dentro de la prenda) encuentran costuras, cierres, franjas y el
     acolchado, con mucho ruido.
   Hace falta: elegir trazos largos, suaves y estables; seguirlos entre cuadros (flujo óptico o
   emparejar por posición); afinar el borde contra el gradiente real para que quede "perfecto"; y,
   donde no alcance, SAM 2 sobre la prenda (ya está en el proyecto para el objeto, ~0,9 s/cuadro).
2. **Coreografía de desfile**: cada outfit elige 2-5 trazos de su prenda (los más largos y de más
   contraste), su calzado, su bolso y una pieza de cabeza, con color propio; entra completo en el corte
   y sale en guiones antes del siguiente. Sin gestos: el foco es la ropa.
3. **Piezas que faltan**: orejas de gato sueltas (hoy van con los ojos felinos), barra de luz sobre los
   ojos, lucecitas sobre el pelo, puntos sobre un patrón de la prenda, zigzag tipo electrocardiograma.
4. **Corte deslizante**: el análisis nuevo (2026-11-02) ve los cortes 27, 59, 90 y 153, pero no el de
   120-122 (paso al outfit naranja): hay que afinar el detector para transiciones de 2-3 cuadros.
5. **Eventos de caminar**: el análisis da `step`, `stomp` y `foot_strike` al andar; en un desfile no
   deben disparar efectos de baile (pisotones).

## Decisión de precisión (2026-11-02)

El usuario eligió el camino rápido: segmentador multiclase más bordes de la imagen, con los trazos
ajustados al borde real de la tela y seguidos entre cuadros. **Mejora futura anotada**: recortar cada
prenda con SAM 2 (el mismo que sigue el objeto, `analysis/props.py`) para un contorno casi perfecto,
a ~0,9 s por cuadro; podría ofrecerse como opción de "alta calidad" al subir el video.

## Implementado (2026-11-02, primera versión)

- `analysis/garment.py`: trazos de la prenda por cuadro (fronteras, accesorios, bordes internos),
  ajustados al borde real y seguidos con ids estables por toma (distancia media de sus puntos; un tramo
  de la misma costura conserva su id). Solo si el guion lo pide.
- `engine/garment_fx.py` (`garment_lines`): elige por outfit los trazos que más aparecen con más
  contraste (calzado y bolso, un par de fronteras, unos bordes internos), los dibuja cuadro a cuadro y
  sale en guiones los últimos 6 cuadros.
- Catálogo `desfile`: eventos `outfit` y `outfit_head` por toma (`outfits: true`), un color distinto
  por outfit (`cut_chapters: true`), piezas de cabeza (cachos, aro, orejas de gato sueltas `cat_ears`,
  visera, gafas si las lleva, corona), espera 0 entre activaciones y `keep_on_cut`.
- Cortes deslizantes de 2-3 cuadros detectados (`analysis/beats.py`): video_46 da 27, 59, 90, 122 y 153.
- El motor reinicia un efecto que pasa sin pausa a otra activación (su fase y su color de capítulo).

Comparado con la referencia, lo que falta afinar: menos trazos de prenda que la referencia (en prendas
oscuras sobre oscuro, como el abrigo, Canny no ve los bordes delanteros), juntar tramos de una misma
costura en una línea larga, el patrón de la prenda (puntos en el acolchado, zigzag), lucecitas en el
pelo, anillos de articulaciones, y que las piezas de cabeza se elijan según el outfit (gafas solo
cuando las lleva).

## Pendiente

- El glowing de `video_55` no está en `glowing/data/glowing/` (solo su original); sin él no se puede
  comparar. Su original es del mismo género: prueba de outfits frente al espejo, sumando capas
  (camiseta y short, sudadera, bomber, mochila), con poses y casi sin movimiento; el análisis nuevo ve
  9 cortes. Según el usuario, usa técnicas de cara neón.
