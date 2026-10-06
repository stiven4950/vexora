# Comandos de trabajo

Referencia de los comandos usados durante el plan de mejoras, agrupados por tarea. Todos se
ejecutan desde la carpeta `vfxglow/` con el entorno virtual activo (`source .venv/bin/activate`)
o anteponiendo `.venv/bin/` a `python` y `vfxglow`.

Los videos de ejemplo viven fuera del repositorio:

| Ruta | Contenido |
| --- | --- |
| `../glowing/data/original/video_N.mp4` | Plano original (entrada del pipeline) |
| `../glowing/data/glowing/video_N.mp4` | Referencia: cómo debería quedar el efecto |

Cada corrida se guarda en `runs/<video>-<hash8>/`. Los runs actuales:

| Run | Video | Preset principal |
| --- | --- | --- |
| `runs/video_1-34f2d20d` | Pelea, 834 fotogramas | `fight_comic` |
| `runs/video_2-e27a6ae3` | Maquillaje y calabaza, 350 | `face_neon`, `paint_reveal` |
| `runs/video_27-6dc78c0f` | Baile, 570 | `doodle_dance` |

## 1. Configuración inicial

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Clave de OpenAI (director artista y lector de escena). La clave va en un archivo local que
git ignora; nunca en un commit ni en el chat:

```bash
cp .env.example .env
# editar .env y poner: OPENAI_API_KEY=sk-...
```

`vfxglow` lee `.env` al arrancar. Una variable ya exportada en la terminal tiene prioridad.

## 2. Generar videos

Pipeline completo con un preset:

```bash
vfxglow run --video ../glowing/data/original/video_1.mp4 --preset fight_comic
vfxglow run --video ../glowing/data/original/video_2.mp4 --preset face_neon
vfxglow run --video ../glowing/data/original/video_2.mp4 --preset paint_reveal
vfxglow run --video ../glowing/data/original/video_27.mp4 --preset doodle_dance
```

El resultado queda en `runs/<video>/output/<preset>.mp4`. Se escribe primero como
`<preset>.partial.mp4` y solo se publica si salieron todos los fotogramas.

Coreografía por catálogo (reacciones sorteadas por acción; ver [catalogo_efectos.md](catalogo_efectos.md)):

```bash
vfxglow run --video ../glowing/data/original/video_1.mp4 --catalog pelea            # semilla del catálogo
vfxglow run --video ../glowing/data/original/video_1.mp4 --catalog pelea --seed 7   # otra coreografía
```

Las decisiones quedan en `runs/<video>/scripts/choreography.json` y el video en
`runs/<video>/output/pelea.mp4`.

Director artista con gpt-5 (necesita la clave; una llamada por video, la respuesta queda en caché):

```bash
vfxglow run --video clip.mp4 --director openai
```

Etapas sueltas y opciones:

```bash
vfxglow analyze --video <video>          # solo análisis y overlay de depuración
vfxglow direct  --video <video> --preset <preset>
vfxglow compose --video <video>
vfxglow run --video <video> --preset <preset> --force          # ignora la caché
vfxglow run --video <video> --preset <preset> --layers glow    # solo algunos grupos de capas
```

La caché se invalida sola si cambia el video, la configuración, el preset o el código de la
etapa. `runs/<video>/manifest.json` → `inputs` dice con qué guion, preset y versión de código
salió cada video, y cuántos fotogramas escribió.

## 3. Revisar resultados

Vista previa de fotogramas sueltos, sin renderizar el video entero (segundos en vez de minutos).
Con `--ref` añade una fila con el mismo fotograma del video de referencia:

```bash
python tools/preview.py --run runs/video_1-34f2d20d \
  --video ../glowing/data/original/video_1.mp4 --preset fight_comic \
  --frames 300,500,584,660 --ref ../glowing/data/glowing/video_1.mp4 --tile 400 --out preview.jpg
```

Con un guion ya dirigido (por ejemplo, una coreografía) en vez de un preset:

```bash
python tools/preview.py --run runs/video_1-34f2d20d --video ../glowing/data/original/video_1.mp4 \
  --script runs/video_1-34f2d20d/scripts/pelea.json --frames 46,352,528 --tile 400
```

Fotograma ↔ segundo: `segundo = fotograma / 30` en estos videos.

Contar los fotogramas de un video generado:

```bash
FF=$(python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())")
$FF -i runs/video_1-34f2d20d/output/fight_comic.mp4 -map 0:v:0 -c copy -f null - 2>&1 | grep -o "frame= *[0-9]*" | tail -1
```

## 4. Regresión

Huella dorada de un preset (hash de cada capa cada 10 fotogramas sobre una copia congelada del
análisis). Se captura una vez y luego se comprueba después de tocar el motor:

```bash
python tools/snapshot.py --run runs/video_2-e27a6ae3 --preset face_neon          # capturar
python tools/snapshot.py --run runs/video_2-e27a6ae3 --preset face_neon --check  # comprobar
```

`--check` devuelve 0 si es idéntico y lista los fotogramas y efectos que cambiaron si no. Tras
un cambio visual aprobado, se vuelve a capturar para que sea la nueva línea base.

Tabla de regresión de los cuatro (video, preset) del plan, en `runs/bench.md`:

```bash
python tools/bench.py               # fotogramas, código vigente, tracking y eventos
python tools/bench.py --snapshots   # además compara las huellas doradas
```

Pruebas unitarias:

```bash
pytest
```

## 5. Historial (git)

```bash
git log --oneline          # un commit por paso del plan
git show <commit> --stat   # qué archivos tocó un paso
git diff baseline          # todo lo cambiado desde el estado original
git checkout baseline -- <archivo>   # recuperar la versión original de un archivo
```

`baseline` es la etiqueta del estado del proyecto antes del plan de mejoras.

| Commit | Paso |
| --- | --- |
| `0c0c7f2` | Estado base (`baseline`) |
| `8a8f4f4` | Etapa 0: huella de código en la caché, salida atómica por preset, `tools/snapshot.py` |
| `02bcbd8` | Etapa 1: `PointSet` con confianza y origen, capa de restricciones |
| `8c9de1f` | Etapa 2: anclas por fotograma, veto de ojos con histéresis, reinicio en cortes |
| `ba31d21` | Etapa 2: respaldo facial con segmentador y ojo claro (plano de la calabaza) |
| `caac3eb` | Etapa 2: fases del golpe y carga por mano en `fight_comic` |
| `fc58927` | Etapa 3: `tools/bench.py` |
| `3e65dcf` | Carga de claves desde `.env` |
| `46f0d49` | `fight_comic` fase 1: swoosh por velocidad con trazo de neón |
| `4bf07c0` | `fight_comic` fase 1b: hebras y modo pintura, `tools/preview.py` |
| `dff64c1` | Este documento de comandos |
| `b998fdb` | `fight_comic` fase 2: llamarada, chispas y gotas (`engine/burst.py`) |
| `52c17be` | Gotas más pequeñas y menos numerosas |
| `e0385ba` | Partículas de varias formas en los puñetazos (gota, anillo, hoja, rizo, guion) |
| `a269d3c` | Llamaradas más pequeñas con tope de tamaño; neón más vívido |
| `5f1a11d` | `fight_comic` fase 3: evento `fist_clash`, energía de choque (`clash`) y brazo musculoso (`engine/limb.py`) |
| `f5bfb62` | Brazo musculoso sin parpadeo (histéresis y fundido) |
| `d9ae577` | Coreógrafo por catálogo (`--catalog pelea`, `--seed`), `body_bump`, rayo de ojos y estrellas |
