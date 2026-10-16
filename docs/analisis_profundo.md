# Análisis profundo con IA

Opción de pago, apagada por defecto. El análisis económico de siempre reacciona a cada gesto
detectado. El profundo le pasa el video completo, con su audio, a Gemini 4 Argon, que lo lee como
un animador: la intención de cada movimiento, la historia del video, la letra de la canción, y
metáforas con historia. Su respuesta se vuelve la coreografía.

Nació de la prueba con video_35 (`docs/metaforas.md`): con el video entero, Argon acertó o se
acercó a 10 momentos de la referencia, escuchó "It's a UFO" y propuso 4 efectos nuevos de buena
calidad. El director con GPT-5 solo ve fotos sueltas por beat.

## Cómo se usa

Necesita `GEMINI_API_KEY` en el `.env` local (nunca en git).

- **Línea de comandos:** `vfxglow run --video <video> --catalog baile --deep`
- **Web:** al subir un video con un estilo de catálogo, paso "Análisis" → "Profundo con IA". En la
  página del video, "Probar otra versión" deja cambiarlo.
- **Configuración:** `director.deep` en `configs/default.yaml` (`enabled`, `model`, `fps`).

Un guion fijado a mano (`--pin`) manda sobre el análisis profundo.

Si el modelo está saturado (error 503, "high demand") o se pasa la cuota por minuto (429), se
reintenta solo 4 veces, esperando 15, 45, 90 y 180 s, sin volver a subir el video. Si sigue
saturado, el error lo dice; el análisis de movimiento ya quedó guardado y reintentar más tarde es
rápido.

## Mixto: la historia de la IA y el relleno del económico

Por defecto (`director.deep.fill: true`), lo que dice el modelo son los momentos principales: van
fijados, con su color e intención. Alrededor, el coreógrafo económico agrega lo de siempre:
acentos, golpes de la música, la otra persona. Sin eso, el modelo pone un efecto cada uno o dos
segundos y en un dúo deja casi sin nada a una persona (`historial/dance_two_mens/`: 24 momentos,
19 en un bailarín y 4 en el otro; mixto: 66, repartidos 38 y 24).

Con dos o más personas, el modelo dice a quién va cada momento (`quien`: izquierda, derecha o
ambos, como se ve en pantalla). Se traduce a cada bailarín por la posición de su caja en ese
segundo. "Ambos" lo copia en la pareja.

## Precisión y fotogramas por segundo

El modelo no necesita ver todos los fotogramas: su trabajo es entender la intención. La precisión
la pone nuestro análisis, que sí los mira todos:

- **Cada momento se ajusta al gesto detectado.** Si nuestro análisis vio ese gesto (la misma
  acción) a menos de 0,3 s, el momento empieza justo ahí; si no, en el golpe de la música a menos
  de 0,15 s. En dance_two_mens se ajustaron 17 de 20 momentos, todos menos de 0,3 s.
- **Fotogramas por segundo automáticos** (`director.deep.fps` sin valor), según los gestos rápidos
  por segundo y por persona que encontró el análisis económico:

  | Gestos rápidos por segundo | Ejemplos | Fotogramas por segundo |
  | --- | --- | --- |
  | Menos de 2,5 | michael_jackson_dance, video_34 | 5 |
  | De 2,5 a 5 | dance_two_mens, video_35 | 8 |
  | Más de 5 | peleas, ninja acróbata | 10 |

  Nunca más de 450 fotogramas en todo el video (`frame_budget`): uno largo baja los fotogramas
  por segundo para cuidar el costo. Con `fps: 12` (por ejemplo) se fija a mano.

## Qué pasa por dentro (`src/vfxglow/director/deep.py`)

1. Arma el prompt de animador con el catálogo real: acciones, opciones y figuras, y qué hacen las
   figuras con historia.
2. Sube el video a la API de archivos de Gemini, pide la respuesta en JSON (a 5, 8 o 10 fotogramas
   por segundo según el baile) y borra el video subido.
3. Revisa la respuesta:
   - corrige la acción si la opción es de otra;
   - descarta lo que no existe en el catálogo o cae fuera del video;
   - limita la duración de cada momento a entre 0,2 y 4 s.
4. La vuelve un guion de prueba con color e intención por momento. El color manda sobre los
   capítulos de color del solista; la intención se ve en el panel de la coreografía de la web.
5. Los efectos que propone y no existen se anotan en `runs/efectos_propuestos.jsonl`, una línea
   por efecto, para programarlos después. Mientras tanto, en su momento va el sustituto más
   parecido que el propio modelo elige.

## Archivos que deja (en `runs/<video>/scripts/`)

| Archivo | Qué es |
| --- | --- |
| `deep_cache/<clave>.json` | La respuesta del modelo. Reprocesar el mismo video con el mismo modelo y prompt no vuelve a pagar |
| `deep_lectura.json` | La lectura completa: protagonista, momento a momento, historia, efectos nuevos |
| `deep_guion.yaml` | El guion que sale de la lectura; se puede editar y correr con `--pin` |

El video sale como `output/<estilo>__deep_guion.mp4`, así que no pisa al del análisis económico.

## Para probar

1. `vfxglow run --video ../glowing/data/original/video_35.mp4 --catalog baile --deep`
2. Comparar con `historial/video_35/` (referencia y guion de Gemini a mano).
3. Revisar `runs/efectos_propuestos.jsonl`: ¿qué efectos nuevos pidió?
4. Probar con un video que no haya visto nunca.

Si la respuesta no convence, se ajusta el prompt (`PROMPT` en `deep.py`). Cambiar el prompt cambia
la clave de caché: la siguiente corrida vuelve a preguntar.
