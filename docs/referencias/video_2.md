# video_2 · Maquillaje y revelado de calabaza (`paint_reveal`)

Lectura de la referencia `glowing/video_2.mp4` (350 fotogramas, 11,7 s) con el criterio de
`docs/criterio_de_analisis.md`, y diagnóstico de nuestra versión (`runs/video_2-e27a6ae3`).

## Dos escenas, dos lenguajes

El video tiene un corte en el fotograma 207 (6,9 s). El creador trata cada escena distinto.

### Escena 1 · La pintura (0–6,9 s)

Primer plano de la cara, luz clara, lentes blancos. Una mano pinta con pincel.

| Seg. | Qué hace la persona | Atención | Referencia | Qué hay que detectar |
| --- | --- | --- | --- | --- |
| 0,2–0,7 | Pincel ancho: banda naranja en la frente | La pintura nueva | Contorno blanco-amarillo que **se va dibujando a medida que avanza el pincel**, con un punto caliente donde toca | El borde de la pintura recién puesta y el punto de contacto |
| 0,7–1,0 | Termina la banda | La banda | El contorno se **deshace en guiones** y se apaga | La edad de cada tramo del contorno |
| 1,0–1,4 | Banda en la mejilla izquierda | La pintura nueva | Igual: contorno nuevo de la mancha nueva, lo anterior se disuelve | — |
| 1,4–2,7 | Nariz y curva de la boca | La pintura nueva | Contorno que crece con la mancha, más brillante junto al pincel | — |
| 2,9–5,0 | Pincel fino: líneas negras de los ojos | La línea que se dibuja | **Una llama corta en la punta** del pincel y la línea recién trazada brillando, fina | La punta del pincel y su recorrido |
| 5,0–6,6 | Nariz y boca negras | La línea que se dibuja | Luz en la punta y la línea de la boca encendida mientras se traza | — |

- **No se ilumina nada más:** ni los ojos, ni el contorno de la cabeza, ni la mano.
- **Color:** cálido, blanco con halo amarillo-naranja, como la pintura.

### Escena 2 · La calabaza (6,9–11,7 s)

Corte a la máscara terminada: fondo oscuro, humo, sin cara humana (Face Mesh no detecta nada).

| Seg. | Referencia | Qué hay que detectar |
| --- | --- | --- |
| 6,9–8,7 | Chispas blanco-cian que suben con el humo desde la cabeza; arcos verdes en las cuencas; puntos azules en los dientes | El humo o la parte de arriba de la cabeza; las cuencas y la boca de la máscara |
| 8,9–9,9 | Trazos cortos azules y verdes **sobre las estrías** de la calabaza (frente y costados) | Las líneas oscuras pintadas |
| 10,3 | Contorno azul de la nariz; estrías verdes en la frente | La nariz de la máscara |
| 10,8 | Líneas verdes bajo los ojos y la nariz azul | Los ojos |
| 11,3 | Líneas rojas bajo los ojos y marcas verticales rojas en los dientes | La boca |

- **Patrón:** acentuar los rasgos de la máscara uno por uno (ojos → estrías → nariz → ojos →
  boca), con trazos cortos que siguen las líneas pintadas, de 0,3–0,6 s cada uno.
- **Color:** frío y cambiante (verde, azul, rojo), opuesto a la escena 1. Es un **cambio de
  capítulo de color por corte de escena**.

## Patrones

1. **Escena de pintura:** la luz sigue al pincel. Lo nuevo se ilumina y lo viejo se apaga.
   - Pincel ancho: contorno de la mancha recién puesta, que se dibuja con el avance y se deshace
     en guiones.
   - Pincel fino: la línea recién trazada y una llama en la punta.
2. **Escena de revelado:** la luz acentúa la obra terminada. Trazos cortos sobre sus líneas,
   rasgo por rasgo y color por color, más chispas con el humo.
3. **Un corte de escena cambia el lenguaje y la paleta.**

## Diagnóstico de nuestra versión

| Problema | Causa | Efecto en el video |
| --- | --- | --- |
| La "pintura nueva" es en realidad **la mano y el pincel** | `analysis/appearance.py` compara con un fondo lento y elige la mancha que toca la muñeca; lo que más cambia es la mano en movimiento | Contornos y llamas alrededor de la mano y abajo del cuadro (fotogramas 31, 41, 130...) en vez de sobre la pintura |
| La punta del pincel cae en la mano o el borde del cuadro | Sale del mismo blob equivocado | `tip_flame` aparece lejos del pincel |
| No hay dibujo progresivo ni disolución | `contour` dibuja el contorno entero con persistencia | No se lee "la luz sigue al pincel" |
| Contorno de la cabeza en la escena 2 | `head_outline` usa el segmentador, que incluye el humo | Una línea amarilla temblorosa alrededor de la cabeza y del humo; la referencia nunca la dibuja |
| Faltan los acentos de la calabaza | No hay detección de las líneas pintadas ni un efecto de trazos cortos secuenciales | Escena 2 sin lo que la hace atractiva |
| Una sola paleta amarilla | El preset no cambia de color en el corte | La escena 2 no contrasta con la 1 |
| Luces en ojos, nariz y boca en la escena 1 | Las pide el preset; los ojos se vetan, pero nariz y boca no | Luces que la referencia no tiene |

## Qué se implementó

| Parte | Implementación |
| --- | --- |
| Detección de la pintura | `analysis/paint.py`: cada fotograma se alinea a la cara del primero; nace pintura donde aparece "no piel" (color o negro) y se queda; la mano, el pincel y el borde que se corre no cuentan. La pintura negra va en su propia capa (se pinta sobre el naranja, en líneas finas) |
| La luz sigue al pincel | `paint_trace`: contorno de la pintura nueva que se dibuja con la edad de cada punto, punto caliente y llamita en la punta, y lo viejo en guiones que se apagan |
| La obra terminada | `detect_accents` + `paint_accents`: líneas oscuras pintadas en la cabeza, por zona (ojos, estrías, nariz, boca); se encienden una zona y un color a la vez, cada 0,45 s |
| Chispas con el humo | `rising_sparks` al empezar la escena de la obra |
| Limpieza | Fuera el contorno de la cabeza y las luces de ojos, nariz y boca; paleta cálida en la pintura y fría y cambiante en la obra |

La detección de pintura se detiene en el primer corte (en la calabaza la malla "ve" una cara).
Pintura y herramienta, sin suponer colores:

- **Pintura:** un píxel es pintura si es distinto de la **piel limpia de ese mismo punto** (mediana
  de los primeros fotogramas, en coordenadas de la cara, con la luz general compensada) y además
  su color no es piel (o es negro donde antes no lo era).
- **Herramienta** (`analysis/tool.py`): en los fotogramas alineados a la cara, lo que se mueve es
  la mano con la herramienta; la punta es su extremo dentro de la cara, lejos de por donde entra.
  Cuenta solo si hay pintura en ese punto (contacto) y si no salta lejos de la punta anterior.
  Funciona con cualquier pincel, esponja o dedo.
- **Efecto:** la llama va en la punta; el recorrido de la punta es la línea fina; con la
  herramienta a la vista, lo recién pintado se ilumina solo cerca de su punta.

Pendiente:

- Algún destello cerca de los ojos en la fase de líneas negras.
- La restricción "cerca de la punta" recorta un poco el contorno completo de las manchas anchas
  (0,5–0,9 s), que la referencia muestra entero.

### Detector de herramienta con modelo (`analysis.paint_tool: model`)

Grounding DINO ("a paintbrush. a makeup brush. a pencil.") cada 6 fotogramas y SAM 2 en cada uno:
encuentra el pincel en todos los fotogramas probados (confianza 0,45–0,72) y su máscara exacta,
incluido el pincel ancho de la primera parte. Cuesta ~2 minutos más en video_2. Resultado visible
casi igual al del movimiento: los destellos cerca de los ojos no venían de la punta sino del
contorno de la pintura negra alrededor de los ojos. Por defecto queda `motion`.
