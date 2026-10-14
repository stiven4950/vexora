# Plan: director con IA que ve la escena y compone efectos nuevos

Estado: propuesta, sin implementar.

## Punto de partida

Hoy el director con IA (`--director openai`, `director/director.py` y `director/art.py`) recibe:

- un resumen del análisis: una línea por momento (beat), con gestos, foco y ritmo;
- la lectura de escena de `gpt-5-mini`;
- 4 fotogramas en baja resolución (`keyframes`, `director.images: 4`).

Devuelve qué estrategia usar en cada momento y dibujos propios trazo a trazo. La respuesta se
guarda en `scripts/director_cache/`.

Sus límites:

- **Ve fotos, no movimiento.** No sabe que la cabeza se movió, que las manos se tocaron o que la
  pareja baila igual, salvo por lo que diga el resumen.
- **Solo elige entre los tipos de efecto que ya existen.** Un comportamiento nuevo (una cinta con
  física, un alma que vuelve como goma, púas que crecen al paso de la mano) hoy necesita código
  nuevo en `engine/`.

El plan tiene dos partes: que vea la escena de verdad (A) y que pueda crear efectos combinando
piezas (B). La autocrítica con render y comparación queda para después (C).

---

## A. Ver la escena de verdad: niveles de análisis

El análisis se ofrece en niveles. El profundo es opcional y cuesta más; queda listo para cuando
se defina el modelo de negocio (ver `docs/plan_cuentas_y_nube.md`, "Planes y permisos").

| Nivel | Qué ve la IA | Qué decide | Costo de IA por video (orden) |
| --- | --- | --- | --- |
| **Básico** | Nada (sin IA) | El coreógrafo sortea con el catálogo | 0 |
| **Estándar** | Resumen + 4 fotogramas (lo de hoy) | Estrategia por momento y dibujos | Centavos |
| **Profundo** (opcional, de pago) | Una tira de fotogramas por cada momento clave, recortada a cada persona, más los datos del análisis | Intención por momento, efectos compuestos (parte B) | Del orden de dólares; se mide en A3 |

El costo exacto depende del modelo, de la resolución de las imágenes y del número de momentos.
`providers.py` ya imprime los tokens de cada llamada; A3 los convierte en una tabla de costo por
video, que es la que fijaría el precio.

### A1. Selección de momentos clave

No se le manda todo el video, solo lo que importa:

- Los tramos de la línea de atención (`brief.attention`) con cambio de foco.
- Los gestos con significado (`analysis/gestures.py`): mano a la cabeza, corazón, giro, pisotón...
- Los tramos de pareja (`brief.duet`): unísono y solo.
- Los cortes de escena (`brief.beats`).
- Contactos entre personas (manos que se tocan).

Se fusionan los que se solapan y se limita a N momentos por video (ej. 12 en profundo). Salida:
`analysis/moments.json` con inicio, fin, personas y motivo.

### A2. Expediente por momento

Por cada momento:

- **Tira de 6-8 fotogramas** repartidos en el tramo, recortados a la caja de cada persona (no el
  cuadro entero: más detalle por token), a 384-512 px.
- **Datos numéricos** del análisis: qué parte se mueve, velocidad y dirección, quién lleva el foco,
  contactos, de frente, de espaldas o de perfil (`facing`, `far_side`), si la pareja va al unísono.

La IA responde con la tabla de `docs/criterio_de_analisis.md` (sección 2), una fila por momento:
qué hace la persona, dónde está la atención, hacia dónde va el movimiento, el gesto y su
significado, y la propuesta de efecto. El criterio completo va en el prompt de sistema.

Salida: `analysis/scene_reading.json`, guardada con el análisis. Es la pieza que el usuario
conserva para reprocesar (ver el plan de cuentas): cambiar de estilo no vuelve a pagar la lectura.

### A3. Medición del costo y la calidad

- Registrar por video: tokens de entrada y salida, número de imágenes, tiempo y costo estimado.
- Validar la lectura contra las referencias ya escritas (`docs/referencias/video_34.md`,
  `video_2.md`, la tabla de video_33 en el criterio). Meta: que identifique al menos el 80% de los
  momentos de la tabla de video_34 con la intención correcta.
- Comparar el resultado de estándar y profundo con `tools/compare_reference.py` sobre video_34.

### A4. Integración

- `director.analysis_level: basic | standard | deep` en la configuración; `--level-ia` en la
  línea de comandos; un selector en la web, con el costo visible.
- La caché del director incluye el nivel en la clave.
- Si el profundo falla (sin clave, límite de la API), se cae al estándar y se avisa.

---

## B. Efectos compuestos: que la IA cree efectos sin escribir código

En lugar de elegir de una lista cerrada, la IA combina **primitivas** con parámetros. Los efectos
hechos a mano para video_34 (`engine/duo_fx.py`) muestran cuáles hacen falta: cada uno es una
combinación de unas pocas piezas.

### B1. Las piezas

| Familia | Piezas | Ejemplos de hoy que se rehacen con ellas |
| --- | --- | --- |
| **Ancla** | articulación, cadena de articulaciones, parte del cuerpo, cabeza, mano que hace el gesto, la pareja, el piso bajo el pie | todos |
| **Geometría** | curva por puntos, cadena del cuerpo (tobillo a mano), aro y elipse, media luna, figura (corazón, nota, estrella, rosa), púas en abanico, silueta de la persona o de una parte | `leg_string`, `head_ring`, `soul`, `punk_hair`, `saco` |
| **Física** | cuerda (Verlet), resorte amortiguado, partículas con deriva | `ribbon`, `soul`, chorro de notas |
| **Movimiento** | órbita 3D alrededor de un eje, giro, seguir a la parte más rápida, revelar al paso de la mano, revelar en el tiempo, crecer y encoger | `orbit_arcs`, `energy_wave`, `punk_hair`, corazones |
| **Trazo** | grosor variable (fino-grueso-fino), relleno blanco con halo de color, ramificar (rayos), guiones | arcos, cintas, rayos |
| **Visibilidad** | ocultar lo que pasa detrás del cuerpo, solo la pierna de adelante, solo la persona del evento | `orbit_arcs`, `leg_string` |

### B2. El formato

Un tipo de efecto nuevo, `compose`, cuyo `style` lleva una lista de capas, cada una con su ancla,
geometría, modificadores y trazo. Va validado con Pydantic (`director/schema.py`), con límites:
capas por efecto, puntos por curva, partículas, duración.

Ejemplo, la cinta de gimnasia escrita como composición:

```yaml
type: compose
layers:
- anchor: {hand: gesture}
  geometry: {rope: {length: 1.6, points: 36}}
  physics: {damping: 0.97, gravity: 0.0008, driver: {circle: 0.45, turn_s: 0.75}}
  stroke: {width: 0.12, taper: tail, twist: 0.9, fill: white, halo: person}
```

### B3. El motor

- `engine/compose.py` interpreta las capas, reutilizando lo que ya existe: `neon_layers`,
  `fill_polygon`, `band`, `visible`, `part_mask`, `catmull_rom`, la cuerda de `_ribbon`, el resorte
  de `soul`.
- El estado entre cuadros (cuerda, resorte) se guarda por efecto y persona, como hoy en
  `runtime.swoosh`.
- Cada efecto de `duo_fx.py` se reescribe como composición y se compara contra el original con
  `tools/snapshot.py`: si se ve igual, el formato alcanza.

### B4. La IA como diseñadora

- El prompt incluye el catálogo de piezas, sus parámetros y ejemplos de composiciones.
- Para cada momento del expediente (A2), la IA propone una composición nueva o un efecto existente.
- La propuesta se valida: si no pasa, se corrige automáticamente una vez con el error; si vuelve a
  fallar, se usa el efecto del catálogo.
- La salida se guarda como **guion de prueba** (`director/pins.py`, ampliado con una sección
  `efectos:` para las composiciones). Así lo que propuso la IA se puede repetir, editar a mano y
  convertir en una opción de catálogo si gusta.

### B5. Pruebas

- Cada pieza dibuja algo en una pose sintética (como `tests/test_pins.py`).
- Las composiciones que reemplazan a `duo_fx.py` dan el mismo resultado (snapshot).
- Una composición inválida (ancla inexistente, parámetros fuera de rango) se rechaza con el motivo.

---

## C. Después: autocrítica

La IA ve su propio resultado y lo corrige: se renderizan solo los tramos de los momentos, se le
muestran junto al original (y a la referencia, si existe, con `compare_reference.py`) y ajusta
parámetros. Multiplica el costo de IA; sería parte del nivel profundo o un nivel aparte.

---

## Orden y entregables

| Fase | Entregable | Criterio de terminado |
| --- | --- | --- |
| A1 | `moments.json` | En video_34 cubre los momentos de la tabla de la referencia |
| A2 | `scene_reading.json` con el expediente | Lectura con la intención correcta en al menos el 80% de esos momentos |
| A3 | Tabla de costo por video y nivel | Costo medido en 3 videos de distinta duración |
| A4 | Niveles en configuración, CLI y web | El nivel profundo se elige y se cobra aparte (cuando exista el plan de cuentas) |
| B1-B3 | `compose` y `engine/compose.py` | Los efectos de `duo_fx.py` reescritos como composición se ven igual |
| B4 | La IA propone composiciones | En video_34 propone efectos nuevos válidos en al menos la mitad de los momentos |
| B5 | Pruebas | Suite en verde |

## Riesgos y límites

- **Costo:** el nivel profundo depende del número de momentos y del precio del modelo, y hay que
  medirlo antes de fijar el precio.
- **Creatividad:** con piezas bien elegidas la IA puede inventar mucho, pero un comportamiento que
  no exista como pieza sigue necesitando código. El catálogo de piezas crece con cada referencia
  nueva.
- **Variabilidad:** dos llamadas pueden dar propuestas distintas. La caché y el guion de prueba
  guardado hacen que el mismo video dé el mismo resultado hasta que se pida otra versión.
- **Proveedor:** el diseño no depende de OpenAI; `providers.py` ya admite otros (`anthropic`).
