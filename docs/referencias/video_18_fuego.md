# Anatomía del fuego de video_18 (seg. 0-3, cuadro por cuadro)

Medido sobre los 91 cuadros de `glowing/video_18.mp4` (720×1280, 30 fps) con
`tools/measure_fire.py`. El fuego se separa por color: cuerpo casi blanco más borde amarillo.

## Lo que pasa en esos 3 segundos

| Cuadros | Seg. | Qué hace el fuego | Medidas |
| --- | --- | --- | --- |
| 0-17 | 0-0,57 | Solo la flecha de Avatar en la frente | 1 pieza de ~1.000 px |
| 18-19 | 0,6 | **Semilla**: una llamita sale de las manos juntas | 995 → 3.772 px |
| 20-25 | 0,67-0,83 | **Crecimiento explosivo**: dos medialunas simétricas (una por brazo) que pasan de V a U y se abren a los lados | 3.772 → 28.705 → 76.642 px; ancho máx. 70-130 px; largo ~800-1.000 px |
| 26-28 | 0,87-0,93 | **Disolución**: la medialuna se vacía por dentro y quedan solo tramos del borde exterior, finos y en punta | piezas: 7 → **21**; área: 76.642 → 18.010 (cae 4 veces en un cuadro) |
| 29-33 | 0,97-1,1 | Dos llamas nuevas suben a los costados y se curvan hacia adentro hasta unirse | 44.607 → 80.123 px |
| 34-39 | 1,13-1,3 | Se juntan en una **columna** que sube por el centro (la energía viaja hacia arriba) | una pieza de 25-40 mil px |
| 40-45 | 1,33-1,5 | **Erupción en el piso**: lóbulos redondos enormes con puntas enroscadas | hasta 160.924 px (un tercio del cuadro) |
| 45-51 | 1,5-1,7 | Dos columnas suben desde el piso hasta arriba y se enroscan hacia adentro en la punta (forma de corazón) | ~50 mil px cada una, largo ~1.450 px |
| 52-57 | 1,73-1,9 | **Disolución**: se rompe en trozos que se achican | piezas: 14 → 22; área: 112.104 → 9.304 en 4 cuadros |
| 58-67 | 1,93-2,23 | Fuego bajo, nace en el piso entre las manos y sube | 20-30 mil px |
| 68-85 | 2,27-2,83 | Dos llamas angostas sobre las manos, que se estiran hacia arriba | 2 piezas de 5-13 mil px, ancho 17-24 px, con 10-20 trocitos alrededor |
| 86-90 | 2,87-3,0 | Un aro que gira alrededor de la mano | ~25 mil px |

## Las reglas que salen de las medidas

1. **Se anima a 30 cuadros por segundo, no "a dos".** Hay 82 dibujos distintos en 91 cuadros. Lo
   que dijo Argon sobre animar a 12 por segundo no vale para esta referencia: el fuego cambia en
   cada cuadro, y solo se repite en unas pocas pausas.
2. **Simetría con los dos brazos.** Cuando el gesto es de las dos manos, salen dos formas espejadas
   (cuadros 20-33 y 45-51).
3. **Vida en tres tiempos:**
   - **Nacer:** de una semilla pequeña a la forma completa en **2 o 3 cuadros** (el área crece unas
     30 veces). La punta avanza primero y el cuerpo la sigue.
   - **Sostenerse:** 3 a 6 cuadros. La forma se abre, se curva y ondula.
   - **Morir:** en **3 a 5 cuadros**. No se vuelve transparente, **se vacía por dentro**: el
     centro de la forma desaparece primero y quedan tramos del borde exterior. Esos tramos son
     medialunas finas con puntas, cada vez más angostas, y luego se apagan. En un solo cuadro el
     área cae a la cuarta parte y las piezas pasan de unas 5 a más de 20.
4. **Las puntas se estiran y se cortan.** Al morir, lo que queda se alarga y se afina, hasta que
   la punta se separa como un trozo suelto que sigue un poco y se apaga.
5. **El fuego viaja de un lugar a otro** (de las manos a los lados, de los lados al centro, del
   centro arriba, del piso a los hombros): cada forma nueva nace donde terminó la anterior.
6. **Proporciones**, en un cuadro de 1.280 px de alto:

   | Forma | Ancho máximo | Largo | Fracción blanca |
   | --- | --- | --- | --- |
   | Medialunas | 70-130 px (6-10% del alto del cuadro) | 800-1.150 px | 0,8-0,9 |
   | Llamas de las manos | 30-55 px | 400-600 px | 0,5-0,8 |
   | Trozos sueltos | 8-40 px | 50-250 px | 0,9 o más |

## El modelo para el motor

Una llama es una **cinta con perfil**: una línea central `C(s)` (s de 0 a 1, de la raíz a la
punta) y un ancho `w(s)`. Sobre eso, el tiempo de vida `u` (0 al nacer, 1 al morir) controla todo:

- **Nacer** (`u` de 0 a 0,2): solo se dibuja hasta `s ≤ avance(u)`, con un avance que acelera al
  final, y el ancho crece detrás de la punta. Así se reproduce el crecimiento de 2-3 cuadros.
- **Sostenerse:** el borde se deforma con ruido coherente (fijo en la raíz, libre en la punta).
- **Morir** (`u` de 0,7 a 1): se aplica un umbral de erosión que sube sobre un campo con dos
  partes:
  - **cercanía a la línea central** (`1 − |n|/w`), para que el centro se vacíe primero y queden
    los bordes;
  - **ruido** en coordenadas de la cinta (s, n), para que el borde que queda se parta en tramos.

  Cada tramo que queda se afina y se achica; las puntas sueltas siguen con la velocidad que
  tenían y se apagan.
- **Simetría:** con gestos de dos manos, la misma cinta espejada respecto al eje del cuerpo.
- **Encadenar:** la raíz de la llama siguiente nace en el final de la anterior.

Todo esto se dibuja en una máscara (cuerpo blanco) y se pinta con lo que ya tenemos: borde
amarillo fino, resplandor amarillo a naranja y luz sobre el escenario.
