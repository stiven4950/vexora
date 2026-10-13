# VFX Glow

Pipeline de efectos visuales por capas. El video original es un plano intocable: el análisis extrae el movimiento, un director describe los efectos en un guion y un motor procedural dibuja capas HDR con transparencia. Esas capas se mezclan encima del plano. Ningún modelo redibuja el fotograma completo.

## Qué hace cada módulo

1. **Análisis** (`fast` por defecto). MediaPipe Tasks estima pose, manos y cara. One Euro y Catmull-Rom estabilizan los puntos. El resultado es `tracks.jsonl`, `events.jsonl` y un `motion_brief.json` corto. El overlay dibuja el esqueleto y los eventos activos.
2. **Director.** Un preset local o un LLM emite un Effect Script. Los efectos pueden encenderse por `triggers` (swing, impacto, contacto) en vez de por un rango fijo de fotogramas.
3. **Motor.** Cintas, trails, partículas, aura, rayos ramificados, grietas, ondas y carga. Cada efecto sale como una capa RGBA. Los grupos `glow`, `particles`, `interaction` y `lightning` se pueden apagar en la composición.
4. **Refinador.** Apagado. Si se enciende, exige CUDA y solo texturiza la máscara de una capa ya dibujada.
5. **Composición.** El plano pasa a luz lineal, cada capa se suma o se mezcla, y la esquina sin efecto queda igual. El audio se copia.

`hq` añade YOLO y RTMW. `masks` añade SAM 2.1 y también exige CUDA. Esos extras no hacen falta para el primer resultado.

La interfaz web (estudio con React + API FastAPI) y cómo arrancarla: [web/README.md](web/README.md).

Los comandos de trabajo (generar, revisar, regresión, historial) están en [docs/comandos.md](docs/comandos.md).
El catálogo de acciones → reacciones y cómo extenderlo está en [docs/catalogo_efectos.md](docs/catalogo_efectos.md).
Las mejoras conocidas que quedan pendientes están en [docs/pendientes.md](docs/pendientes.md).

## Requisitos

- Python 3.11 o superior
- ffmpeg, o el binario que instala `imageio-ffmpeg`
- MediaPipe 0.10.x. La serie 1.x aborta en macOS al abrir el grafo con Metal.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

La primera pasada de análisis descarga los modelos de MediaPipe en `models/`.

## Uso

```bash
vfxglow run --video clip.mp4 --config configs/default.yaml --preset avatar_storm
```

Presets incluidos: `avatar_fire`, `neon_joints`, `body_aura`, `face_runes`, `avatar_storm`, `fight_comic`, `doodle_dance`, `paint_reveal`, `face_neon`.

`face_neon` usa la malla facial: delineado de cejas, ojos, labios, nariz y óvalo que se traza poco a poco y se queda, anillos que giran sobre cada iris y cambian de color, y la llama en la punta del pincel.

Director artista (gpt-5, una llamada por video, unos centavos):

```bash
export OPENAI_API_KEY=...
vfxglow run --video clip.mp4 --director openai
```

Recibe una línea por beat, la lectura de escena y 4 fotogramas en baja resolución. Devuelve qué estrategia usar en cada beat y sus propios dibujos trazo a trazo en coordenadas de la cara, el cuerpo o una mano. La respuesta se guarda en `scripts/director_cache/`: repetir la corrida no vuelve a pagar mientras el prompt no cambie. Cada llamada imprime sus tokens.

`fight_comic`, `doodle_dance` y `paint_reveal` salen del catálogo de estrategias (impacto, dibujo y pintura). El lector de escena usa `gpt-5-mini` si existe `OPENAI_API_KEY`; sin esa clave el director sigue con el preset. El extra `scene` instala PySceneDetect y librosa; si no están, los beats se calculan con histograma y flujo espectral.

`run` y `compose` renderizan y mezclan en memoria, sin capas en disco. `vfxglow render` o `engine.keep_layers: true` guardan las capas (~7 MB por fotograma y efecto) para depurar o para el refinador. `--layers glow,lightning` deja fuera partículas e interacción. El extra `objects` (`pip install -e ".[objects]"`) activa YOLO11n para gorra, botella y otros props.

Etapas sueltas, por si solo quieres repetir una:

```bash
vfxglow analyze --video clip.mp4 --config configs/default.yaml
vfxglow direct --video clip.mp4 --config configs/default.yaml --preset neon_joints
vfxglow render --video clip.mp4 --config configs/default.yaml
vfxglow compose --video clip.mp4 --config configs/default.yaml
```

`--force` ignora la caché. Cada corrida vive en `runs/<video>-<hash>/`:

```text
manifest.json                 # clave e insumos legibles de cada etapa
analysis/tracks.jsonl
analysis/events.jsonl
analysis/motion_brief.json
analysis/debug_overlay.mp4
scripts/effect_script.json    # último guion dirigido
scripts/<tema>.json           # guion de cada preset
layers/index.json
layers/<efecto>/f000000.npy
output/<tema>.mp4             # p. ej. output/face_neon.mp4
golden/                       # huellas de tools/snapshot.py y copia congelada del análisis
```

La clave de cada etapa incluye la huella del código del que depende (`analysis/`, `director/`, `engine/`, `composite/`). Cambiar ese código invalida la caché sin tocar etiquetas a mano. `manifest.json` → `inputs` dice con qué guion, preset y versión de código salió cada video, y cuántos fotogramas escribió.

El video se escribe primero como `<tema>.partial.mp4` y solo se renombra si ffmpeg termina y se escribieron todos los fotogramas. Un proceso cortado no deja un video truncado con el nombre final.

`output/final.mp4` de corridas anteriores es un formato viejo: no se sabe con qué código salió. Conviene borrarlo o ignorarlo.

## Guion de prueba: fijar qué efectos salen

Con un catálogo, la coreografía se sortea (siempre igual para la misma semilla). Para comprobar un
efecto, un guion de prueba dice qué sale y cuándo, y el video sale exactamente así:

```yaml
# configs/pruebas/ejemplo_baile_duo.yaml
catalogo: baile_duo
solo_estos: true                                  # solo lo fijado: sin sorteo ni efectos `always`
momentos:
- {seg: 3.0, opcion: bola_espejos}                # efecto de escena
- {seg: 10.2, opcion: saco, persona: person_1}    # solo en esa persona
- {seg: 24.0, opcion: rodillas, espejo: true}     # también en la pareja
- {seg: 11.2, accion: hand_ear, opcion: corona}   # sobre el gesto detectado ahí
```

```bash
vfxglow run --video "../glowing/data/original/video_34 (1).mp4" --pin configs/pruebas/ejemplo_baile_duo.yaml
```

- Cada momento se engancha al evento detectado de su acción más cercano (a menos de 0,5 s, de
  esa persona). Si no hay ninguno, se crea uno en ese instante: el efecto se puede probar aunque
  el análisis no haya visto el gesto.
- `accion` hace falta solo si la opción está en varias acciones. `espejo` sin valor sigue la regla
  del catálogo (`duet`). `dur` es lo que se ve el efecto (0,6 s por omisión).
- `exacto: true` crea el momento justo en `seg` aunque haya un evento detectado cerca (para calcar
  una referencia); `lado: left|right` dice qué mano o pie.
- `configs/pruebas/video_34_referencia.yaml` calca la referencia de video_34 momento a momento.
- Con `solo_estos: false`, lo fijado se respeta y el resto se sortea alrededor.
- Lo fijado no se apaga fuera del foco de atención.
- Lo que no se puede cumplir (opción inexistente, persona que no está, segundo fuera del video)
  detiene la corrida con el motivo.
- Una coreografía que gustó se convierte en guion para fijarla o editarla:
  `vfxglow pin-export --choreography runs/<run>/scripts/<tema>.choreography.json --out configs/pruebas/x.yaml`.

`tests/test_pins.py` fija, uno por uno, todos los efectos de `baile_duo` sobre una pareja
sintética y falla si alguno no dibuja nada.

## Gate de regresión

```bash
python tools/snapshot.py --run runs/video_2-e27a6ae3 --preset face_neon          # captura
python tools/snapshot.py --run runs/video_2-e27a6ae3 --preset face_neon --check  # compara
```

Renderiza en memoria y compara un hash por efecto cada 10 fotogramas. Un cambio del motor que no debía alterar un preset se detecta sin mirar el video.

## Director remoto

En `configs/default.yaml`, `director.provider` puede ser `openai` o `anthropic`. La clave se lee de `director.api_key_env`. El modelo no elige píxeles: si pide un tipo de efecto desconocido, el validador lo rechaza.

## Opciones que piden CUDA

- `analysis.level: masks` y el checkpoint de SAM 2.1 en `analysis.masks.sam2_checkpoint`
- `refiner.enabled: true`

Sin CUDA el proceso se detiene al arrancar, antes de gastar el video. En CPU o Apple Silicon el camino `fast` más el motor procedural es el que corresponde.

## Pruebas

```bash
pytest
```
