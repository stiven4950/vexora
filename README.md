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

Catálogos de un solo elemento (`--catalog fuego|agua|rayo|tierra|viento`): salen de `avatar.yaml` con
`extends` y `only_element` (y `keep` para conservar opciones neutras por nombre); el catálogo `avatar`
sigue mezclando los cinco elementos en capítulos. Rayo y tierra son más sobrios porque la base tiene
pocas opciones de esos elementos (5 y 16).

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

## Cuentas (Firebase Auth)

La web pide entrar con Google y la API solo responde con una sesión válida; cada usuario ve solo sus
trabajos. Configuración:

- **Web:** `web/.env.local` con la configuración web de Firebase (plantilla en `web/.env.example`).
- **API:** en `.env`, `VEXORA_FIREBASE_PROJECT` (el ID del proyecto, p. ej. `vexora-dev`) y
  `VEXORA_SECRET` (firma de las URLs de archivos). `pip install -e ".[api]"` instala `firebase-admin`.
- **Firebase:** activar Google en Authentication → Sign-in method. `localhost` ya está entre los
  dominios autorizados; un dominio propio hay que agregarlo.

Detalles:

- Las peticiones llevan `Authorization: Bearer <ID token>`. Videos, miniaturas y progreso usan URLs
  con una llave corta (`?k=`), firmada y ligada al trabajo y al usuario, que caduca en 6 horas.
- El trabajo de otro usuario responde 404.
- Los trabajos de antes de las cuentas los adopta, al entrar, el correo de `VEXORA_LEGACY_OWNER`.
- `VEXORA_AUTH=off` desactiva la verificación (usuario local) para desarrollo; el servidor se
  niega a arrancar así fuera de `127.0.0.1`. Sin `VITE_FIREBASE_API_KEY`, la web no pide sesión.
- La adopción de `VEXORA_LEGACY_OWNER` exige el correo verificado: cualquiera puede registrar un
  correo ajeno con contraseña.

## Límites de la API

Cada video se lee con ffmpeg antes de encolarlo: un archivo que no es video, demasiado largo o
demasiado grande se rechaza con un mensaje claro (`api/limits.py`). Con la autenticación activa,
cada usuario tiene cuotas. El análisis profundo, que es de pago, está cerrado salvo para las
cuentas de `VEXORA_DEEP_ALLOW`.

| Variable | Por omisión | Qué limita |
| --- | --- | --- |
| `VEXORA_MAX_VIDEO_SECONDS` | 180 | Duración del video |
| `VEXORA_MAX_VIDEO_SIDE` | 2160 | Píxeles del lado largo |
| `VEXORA_MAX_ACTIVE_JOBS` | 2 | Trabajos en cola o procesando a la vez, por usuario |
| `VEXORA_DAILY_JOBS` | 20 | Trabajos por usuario en 24 h |
| `VEXORA_DEEP_ALLOW` | (nadie) | Uids o correos con análisis profundo, separados por comas; `*` = todos |
| `VEXORA_DAILY_DEEP` | 2 | Análisis profundos por usuario en 24 h |
| `VEXORA_DAILY_DEEP_GLOBAL` | 20 | Análisis profundos de todos en 24 h |

Una cuota agotada responde 429. Un trabajo que falló se reintenta con `POST /api/jobs/{id}/retry`
(botón "Reintentar" en la web). `POST /api/jobs/{id}/cancel` cancela uno en cola (se borra ya) o en
curso (se corta en unos segundos, en el siguiente punto de control del análisis o del render) y borra
todo lo que se había hecho con él. `PATCH /api/jobs/{id}` renombra el proyecto (el video y sus
versiones). La persona ve un mensaje claro (`error_code` + `error`); el
detalle técnico queda solo en el registro del servidor.

Borrar un trabajo borra también su MP4 (`api_data/outputs/<id>.mp4`) y, si ningún otro trabajo
los usa, el video subido y su carpeta de análisis en `runs/`. Un trabajo que se está procesando
no se puede borrar (409).

## Editor de efectos

Una versión terminada de una coreografía se puede editar en la web (`/app/projects/<id>/edit`):
apagar una pista, quitar, mover o alargar un efecto, agregar uno del catálogo, y cambiar el color,
la intensidad y el tamaño de una pista. Aplicar los cambios crea una versión nueva; las anteriores
se conservan.

- Se edita el guion compilado de la versión (`director/edits.py`), no la coreografía: cada efecto
  lleva sus disparos exactos y su azar sale de su `id`, así que lo que no se toca sale igual.
- Al terminar, cada versión guarda en `api_data/outputs/` su guion (`<id>.script.json`), sus
  momentos (`<id>.moments.json`) y los gestos con que se dibujó (`<id>.events.json`). Las versiones
  hechas antes del editor no los tienen: "Preparar para editar" (`POST /api/jobs/{id}/prepare-edit`)
  los regenera en segundos con el análisis guardado, y su primera edición se dibuja completa.
- Hay una pista por tipo de efecto (máximo 40; el resto va en "Otros efectos"). Los efectos
  permanentes (`always_*`) son pistas que duran todo el video: se apagan o se estilizan, no se mueven.
- Solo se vuelve a dibujar el tramo que cambia (`changed_window`): las activaciones que cambiaron
  más las de cualquier efecto que se cruce con ellas, con 2 s de calentamiento antes que no se
  escriben. El resto del video se copia de la versión anterior.
- API: `GET /api/jobs/{id}/editor` (pistas, momentos y opciones para agregar), `POST
  /api/jobs/{id}/edit` (`{edits: [...]}`; un cambio imposible responde 422) y
  `GET /api/jobs/{id}/filmstrip?n=12` (tira de fotogramas).
- Vista previa antes de aplicar: `POST /api/jobs/{id}/preview` (`{edits, at}`) dibuja 3 s alrededor
  del cabezal con el motor real, sin crear versión (≈ 35 s; en caché, al instante). Comparte una
  cuota diaria por usuario (`VEXORA_DAILY_PREVIEWS`, 60) con la del Estudio.
- Versiones del proyecto (`/app/projects/<id>/versions`): comparador A/B en cortina o lado a lado y
  tabla de diferencias.

## Análisis al subir y recomendación de estilo

El Estudio sube el video en cuanto se elige (`POST /api/uploads`) y un hilo aparte lo analiza
mientras la persona escoge el estilo. Al crear el trabajo con `upload_id`, el análisis ya está (o
el trabajo espera a que termine: hay un candado por carpeta de análisis) y no se repite.

- Solo reutilizan ese análisis los estilos sin `needs` (Avatar, los cinco elementales y Pelea).
  Baile neón (accesorios) y Espadas (hojas) cambian la configuración del análisis y lo rehacen.
- Al terminar, `director/recommend.py` recomienda hasta 3 estilos sin IA: pareja que baila la mayor
  parte del video → Baile; dos personas con contacto → Pelea; hojas detectadas → Espadas;
  volteretas o mucha energía → Fuego o Rayo; siempre Avatar al final. Lo usa "Sorpréndeme con IA".
- Máximo 3 subidas analizándose por usuario; las que no se usan caducan a las 24 h.
- Con la subida lista se calculan avisos de calidad (`analysis/quality.py`): nadie a la vista,
  seguimiento pobre, cuerpo fuera de cuadro, persona pequeña, mucha gente, video corto. Avisan, no
  bloquean.
- "Con efectos" en el Estudio: `POST /api/uploads/{id}/preview` dibuja ~3 s del tramo más activo con
  el estilo elegido (≈ 30 s), sin crear trabajo ni escribir en la carpeta de `runs/`. No está
  disponible en estilos con `needs` (analizan el video a su manera).
- API: `POST /api/uploads`, `GET /api/uploads/{id}` (estado, recomendación y avisos) y
  `DELETE /api/uploads/{id}`.

## Trazabilidad (eventos JSON)

La API y la línea de comandos escriben un evento JSON por línea en `logs/events.jsonl` (rota a
los 20 MB). La consola de la API también sale en JSON (`VEXORA_LOG_FORMAT=text` para leerla a ojo).
Todos los eventos llevan hora UTC con milisegundos, `service`, `env` (`VEXORA_ENV`), `version`,
`job_id` y `trace_id`. Los campos siguen OpenTelemetry y los atributos reservados de Datadog,
para que Grafana (Loki) primero y Datadog después lean las mismas líneas.

| Evento | Qué mide |
| --- | --- |
| `http.request` | Ruta plantilla, estado, duración, IP truncada (sin la llave `?k=`) |
| `upload.received` | Bytes y cabecera del video (duración, resolución, fps, códec) |
| `job.queued` / `job.started` / `job.finished` / `job.failed` / `job.retried` / `job.deleted` | Estilo y opciones, profundidad de la cola, espera en cola, duración total, resumen `metrics` |
| `stage.started` / `stage.finished` | `analyze`, `direct`, `deep`, `render`, `compose`: duración, CPU, caché, resultado |
| `llm.call` | Proveedor, modelo, nivel, propósito, tokens, latencia, caché, respaldo usado, costo estimado |
| `security.*` | `auth_failed`, `media_key_invalid`, `quota_exceeded` |

El costo estimado sale de `configs/llm_prices.yaml` (USD por millón de tokens). Con el precio vacío,
el evento lleva `cost_usd_est: null`: el costo se mide, no se inventa. Nunca se registran correos,
tokens, llaves de archivos ni prompts; el usuario va como hash de su uid. `VEXORA_ENV=prod` deja
de servir `/docs` y `/openapi.json`.

## Guion de prueba: fijar qué efectos salen

Con un catálogo, la coreografía se sortea (siempre igual para la misma semilla). Para comprobar un
efecto, un guion de prueba dice qué sale y cuándo, y el video sale exactamente así:

```yaml
# configs/pruebas/ejemplo_baile.yaml
catalogo: baile
solo_estos: true                                  # solo lo fijado: sin sorteo ni efectos `always`
momentos:
- {seg: 3.0, opcion: bola_espejos}                # efecto de escena
- {seg: 10.2, opcion: saco, persona: person_1}    # solo en esa persona
- {seg: 24.0, opcion: rodillas, espejo: true}     # también en la pareja
- {seg: 11.2, accion: hand_ear, opcion: corona}   # sobre el gesto detectado ahí
```

```bash
vfxglow run --video "../glowing/data/original/video_34 (1).mp4" --pin configs/pruebas/ejemplo_baile.yaml
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

`tests/test_pins.py` fija, uno por uno, todos los efectos de `baile` sobre una pareja
sintética y falla si alguno no dibuja nada.

## Comparar contra la referencia, cuadro a cuadro

```bash
python tools/compare_reference.py --original <original>.mp4 --reference <glowing>.mp4 \
    --ours runs/<run>/output/<tema>.mp4 --tracks runs/<run>/analysis/tracks.jsonl --out runs/<run>/compare
```

En cada fotograma empareja el instante (la referencia puede ir corrida unos cuadros; el
corrimiento se mide a lo largo del video), alinea la imagen, saca la luz que cada versión añadió
sobre el original y la compara por persona: si los dos dibujan, y si es en la misma parte del
cuerpo (tolerancia de un tercio del ancho de hombros). Escribe `frames.csv` (por fotograma y
persona) y `mismatches.json` (tramos donde falta, sobra o está en otro lugar) e imprime el
porcentaje de coincidencia.

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
