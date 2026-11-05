# Despliegue en Google Cloud Run (API + trabajadores) con Firestore y Firebase Storage

La web va a **Firebase Hosting** (que reenvía `/api/**` a la API); la API de Python y los
trabajadores, a Cloud Run, todo en el mismo proyecto de
Google Cloud que Firebase (`VEXORA_FIREBASE_PROJECT`, hoy `vexora-dev`). Región recomendada:
**us-east1**, la misma del bucket (`vexora-dev.firebasestorage.app`), para no pagar tráfico entre
regiones ni sumar latencia al subir y bajar videos.


## Atajo: `scripts/deploy_cloud.sh`

Lo que falta hacer antes de desplegar y de abrir al público: [pendientes_despliegue.md](pendientes_despliegue.md).

Hace todo lo de esta guía con la configuración recomendada (API que escala a cero, trabajadores
como Cloud Run Job que se apaga sin trabajo, web en Firebase Hosting):

```bash
brew install --cask google-cloud-sdk        # una vez: el CLI de Google Cloud (gcloud)
gcloud auth login && gcloud config set project vexora-dev
firebase login
META_API_KEY=... OPENAI_API_KEY=... GEMINI_API_KEY=... scripts/deploy_cloud.sh setup   # una vez
VEXORA_DEEP_ALLOW="tu@correo.com" scripts/deploy_cloud.sh all                          # construir y desplegar
```

`META_API_KEY` es la del análisis profundo por defecto (Muse Spark); las otras dos son opcionales.
`VEXORA_DEEP_ALLOW` (correos o uids con comas, `*` = todos) dice quién puede pedir el análisis
profundo; sin ella, nadie.

`setup` activa las APIs y crea el repositorio de imágenes, la cuenta de servicio con sus permisos,
los secretos y el CORS y el ciclo de vida del bucket. `build` construye la imagen en Cloud Build (no
en tu máquina). `deploy` publica índices y reglas, el Job de trabajadores, la API y la web. Las
secciones de abajo explican cada paso por si hay que hacerlo a mano.

## Qué cambió en el código

| Pieza | Local (por defecto) | Nube |
| --- | --- | --- |
| Documentos (trabajos, subidas) | `api_data/jobs.json`, `api_data/uploads.json` (`JsonDocStore`) | Firestore, colecciones `jobs` y `uploads` (`FirestoreDocStore`) |
| Archivos (videos, salidas, artefactos del editor, capas) | `api_data/uploads/…`, `api_data/outputs/…` (`LocalBlobStore`) | Bucket de Firebase Storage con las mismas claves (`GcsBlobStore`) |
| Cola de trabajos | 1 hilo de la API | Servicio `vexora-worker` con N trabajadores; la API solo encola |

- `src/vfxglow/store/`: `DocStore` (get, set, update con condición, delete, consultas de
  igualdad con orden y límite, `transact` atómico) y `BlobStore` (put, fetch, exists, delete, por
  prefijo, URL firmada). Se eligen con `VEXORA_STORE` y `VEXORA_BLOBS`.
- `src/vfxglow/api/workqueue.py`: la cola son los propios documentos de trabajo (`priority`,
  `worker`, `lease_until`, `attempts`, `cancel_requested`). Tomar un trabajo es una transacción
  (más prioridad primero, luego el más viejo). El trabajador renueva su turno cada tercio de
  `VEXORA_LEASE_S`; si muere, el turno vence y el trabajo vuelve a la cola (hasta 3 intentos;
  después falla como "interrupted"). Cancelar desde la API marca `cancel_requested` y el
  trabajador lo ve en sus puntos de control (lo consulta como mucho una vez por segundo).
- El avance (etapa, porcentaje, consola) se escribe en el almacén como mucho una vez por segundo;
  el SSE de la API lo lee de ahí cada segundo.
- La API sirve un archivo desde su disco si lo tiene; si no, redirige (307) a una URL firmada del
  bucket que vale 15 minutos.
- `jobs.json` y `uploads.json` conservan su formato (lista de documentos): no hay migración. La
  primera vez que el código nuevo abre cada archivo deja una copia `*.json.pre-store.bak` al lado.
- Un cambio de comportamiento también en local: la cola ahora es persistente. Si el servidor se
  reinicia, lo que estaba **en cola** se procesa al volver (antes fallaba como "interrupted"); lo
  que estaba **procesándose** sin turno (código anterior) sigue fallando como "interrupted".

## Imagen

Una sola imagen (`Dockerfile`, `python:3.12-slim` + ffmpeg, extras `api,cloud,objects` con torch
CPU, `configs/`, `assets/`, `models/`). Dos comandos:

- API (comando por defecto): `vfxglow-api` escuchando en `$PORT`.
- Trabajadores: `vexora-worker` (o `python -m vfxglow.worker`).

```bash
PROJECT=vexora-dev
REGION=us-east1
IMAGE=$REGION-docker.pkg.dev/$PROJECT/vexora/vexora:$(date +%Y%m%d-%H%M)

gcloud artifacts repositories create vexora --repository-format=docker --location=$REGION
gcloud builds submit --tag $IMAGE .          # o: docker build --platform linux/amd64 -t $IMAGE . && docker push $IMAGE
```

La imagen no lleva secretos (`.dockerignore` excluye `.env`, `api_data/`, `runs/`, la web y las
pruebas).

## Cuenta de servicio y permisos

Crea una cuenta de servicio para los dos servicios (p. ej. `vexora-run@$PROJECT.iam.gserviceaccount.com`)
con estos roles:

| Rol | Para qué |
| --- | --- |
| `roles/datastore.user` (Cloud Datastore User) | Leer y escribir Firestore |
| `roles/storage.objectAdmin` sobre el bucket | Subir, leer y borrar videos y salidas |
| `roles/iam.serviceAccountTokenCreator` de la cuenta **sobre sí misma** | Firmar las URLs del bucket: en Cloud Run no hay llave privada y se firma con la API de IAM (`signBlob`) |
| `roles/secretmanager.secretAccessor` | Leer los secretos al arrancar |

```bash
SA=vexora-run@$PROJECT.iam.gserviceaccount.com
gcloud iam service-accounts create vexora-run
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/datastore.user
gcloud storage buckets add-iam-policy-binding gs://vexora-dev.firebasestorage.app --member=serviceAccount:$SA --role=roles/storage.objectAdmin
gcloud iam service-accounts add-iam-policy-binding $SA --member=serviceAccount:$SA --role=roles/iam.serviceAccountTokenCreator
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
```

En Cloud Run **no** se usa `GOOGLE_APPLICATION_CREDENTIALS`: las librerías toman la identidad de
la cuenta de servicio del servicio. La llave JSON es solo para correr en local contra la nube.

## Secretos

En Secret Manager, nunca en la imagen ni en variables en texto plano: `VEXORA_SECRET` (firma de
las URLs `?k=`; **debe ser el mismo en todas las instancias**, si no, una URL emitida por una
instancia no vale en otra), `GEMINI_API_KEY`, `OPENAI_API_KEY`.

```bash
printf '%s' "$(openssl rand -hex 32)" | gcloud secrets create vexora-secret --data-file=-
printf '%s' "<clave>" | gcloud secrets create gemini-api-key --data-file=-
```

## Firestore: índices

La consulta de la cola (`status == "queued"`, `worker == null`, orden por `priority` descendente y
`created` ascendente) necesita un índice compuesto. Está en `firestore.indexes.json` (junto con
excluir del índice los campos grandes: `log`, `activity`, `metrics`, `edits`). Sin él, los
trabajadores fallan al buscar trabajo con "The query requires an index". Las demás consultas son
de igualdad y Firestore las resuelve con los índices de un solo campo.

`firebase.json` (en la raíz del repositorio) apunta al índice y a las reglas cerradas de Firestore
(`firestore.rules`) y de Storage (`storage.rules`); `.firebaserc` fija el proyecto `vexora-dev`:

```bash
firebase login                                   # una vez, con tu cuenta de Google
firebase deploy --only firestore:indexes,firestore:rules,storage
```

El índice tarda unos minutos en construirse (consola de Firebase → Firestore → Índices).

Con `VEXORA_FIRESTORE_PREFIX` (p. ej. `staging_`) las colecciones se llaman `staging_jobs`: el
índice compuesto se declara por nombre de colección, así que hay que duplicarlo con ese nombre.

Las reglas de seguridad de Firestore pueden negar todo acceso desde clientes: solo la API y los
trabajadores (cuenta de servicio) leen y escriben, y las cuentas de servicio no pasan por las reglas.

## Servicios

### API

```bash
gcloud run deploy vexora-api --image $IMAGE --region $REGION --service-account $SA \
  --allow-unauthenticated --port 8080 --cpu 2 --memory 4Gi --timeout 3600 \
  --min-instances 0 --max-instances 1 --session-affinity \
  --set-env-vars VEXORA_ENV=prod,VEXORA_STORE=firestore,VEXORA_BLOBS=gcs,VEXORA_BUCKET=vexora-dev.firebasestorage.app,VEXORA_FIREBASE_PROJECT=$PROJECT,VEXORA_INPROCESS_WORKERS=0,VEXORA_PROXY_HOPS=2 \
  --set-secrets VEXORA_SECRET=vexora-secret:latest,GEMINI_API_KEY=gemini-api-key:latest
```

- `VEXORA_INPROCESS_WORKERS=0`: la API no procesa trabajos (lo hacen los trabajadores).
- `VEXORA_PROXY_HOPS=2`: detrás de Firebase Hosting, `X-Forwarded-For` termina en
  `<cliente>, <Hosting>` (Hosting agrega al cliente y Cloud Run agrega a Hosting): la IP real es la
  segunda desde la derecha, y es la que usan los límites de las páginas públicas (api/ratelimit.py),
  no las que puede inventar el cliente. Llamando a la URL directa de Cloud Run sería 1. **Verifícalo
  en el primer despliegue**: con 30 recargas seguidas de un enlace compartido desde tu navegador, la
  31 debe responder 429 a ti, no a todos.
- `--max-instances 1` por ahora: las vistas previas del editor y del Estudio, las capas y el
  análisis de las subidas siguen en hilos de la API con estado en memoria y en su disco (ver
  "Limitaciones").
- `--timeout 3600`: el SSE de progreso mantiene la conexión abierta mientras dura el trabajo.
- Subidas de hasta 500 MB: Cloud Run limita el cuerpo de una petición HTTP/1 a 32 MiB. Para
  videos más grandes hay que subir directo al bucket con una URL firmada de subida (siguiente paso)
  o usar HTTP/2 extremo a extremo (`--use-http2`, que pide que el servidor hable h2c).

### Trabajadores

Opción A, servicio con CPU siempre asignada (el trabajador busca trabajo en segundo plano, sin
peticiones HTTP; `vexora-worker` responde 200 en `$PORT` para que Cloud Run lo dé por sano):

```bash
gcloud run deploy vexora-worker --image $IMAGE --region $REGION --service-account $SA \
  --command vexora-worker --no-allow-unauthenticated --no-cpu-throttling \
  --min-instances 1 --max-instances 3 --concurrency 1 --cpu 4 --memory 8Gi \
  --set-env-vars VEXORA_ENV=prod,VEXORA_STORE=firestore,VEXORA_BLOBS=gcs,VEXORA_BUCKET=vexora-dev.firebasestorage.app,VEXORA_FIREBASE_PROJECT=$PROJECT,VEXORA_WORKERS=1 \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest,OPENAI_API_KEY=openai-api-key:latest
```

- `--no-cpu-throttling` y `--min-instances 1`: sin eso Cloud Run congela la CPU entre peticiones
  y el trabajador no avanza.
- El autoescalado de Cloud Run mira las peticiones HTTP, no la cola: con más trabajo hay que
  subir `--min-instances` a mano (o con un job programado que lea la profundidad de la cola).
- `VEXORA_WORKERS=1` por instancia: el análisis ya usa todos los núcleos. Más trabajos a la vez =
  más instancias.
- Opción B, **Cloud Run worker pools** (pensados justo para esto: sin HTTP ni puerto), si están
  disponibles en el proyecto: `gcloud beta run worker-pools deploy vexora-worker --image $IMAGE
  --command vexora-worker ...` con las mismas variables.
- Opción C, **Cloud Run Jobs**: un job que corre `vexora-worker` hasta vaciar la cola; tendría que
  salir solo cuando no haya trabajo (hoy espera para siempre). Útil si los trabajos son raros.

Al apagarse una instancia (SIGTERM, ~10 s de gracia) el trabajador deja de tomar trabajos; el que
estaba en curso vuelve a la cola cuando vence su turno (`VEXORA_LEASE_S`, 60 s por defecto).

## Storage: CORS

Los `<video>` y `<img>` no necesitan CORS para reproducir una URL de otro dominio. Hace falta si la
web lee los píxeles (canvas/WebGL del editor con capas) o usa `fetch` sobre esos archivos:

```json
[{ "origin": ["https://vexora-dev.web.app", "https://<tu-dominio>", "http://localhost:5173"], "method": ["GET", "HEAD"], "responseHeader": ["Content-Type", "Range", "Accept-Ranges", "Content-Length"], "maxAgeSeconds": 3600 }]
```

```bash
gcloud storage buckets update gs://vexora-dev.firebasestorage.app --cors-file=cors.json
```

Y en ese caso los elementos que leen píxeles llevan `crossOrigin="anonymous"`.

## Web: Firebase Hosting

La web (React, `web/dist`) se publica en Firebase Hosting, en el mismo proyecto. `firebase.json`
(raíz del repositorio) ya trae todo:

- `/api/**` se reenvía al servicio de Cloud Run `vexora-api` en `us-east1`: la web y la API quedan
  en el **mismo dominio**, sin CORS. Si el servicio o la región cambian, se cambian ahí.
- Cualquier otra ruta devuelve `index.html` (la web es una SPA con rutas propias).
- `/assets/**` (con hash en el nombre) se guarda en caché un año; `index.html` nunca, para que cada
  despliegue se vea al instante. Cabeceras de seguridad para toda la web (nosniff, sin iframes,
  HSTS, sin cámara/micrófono/ubicación).
- `predeploy` construye la web antes de subirla.

```bash
# Las variables VITE_ se leen al construir: en web/.env.production.local (no se sube a git)
# pon la configuración de Firebase (web/.env.example explica cada una).
firebase deploy --only hosting
# Una vista previa en un enlace temporal, sin tocar el sitio público:
firebase hosting:channel:deploy prueba --expires 7d
```

Dominio propio: consola de Firebase → Hosting → **Agregar dominio personalizado**. Después pon
ese dominio como `VITE_FIREBASE_AUTH_DOMAIN` y agrégalo en Authentication → Configuración →
Dominios autorizados: así "Iniciar sesión con Google" funciona también en Safari y en navegadores
que bloquean cookies de terceros.

**Límite de 60 s por petición reenviada.** Firebase Hosting corta a los 60 s las peticiones que
pasa a Cloud Run. Por eso nada largo pasa por ahí: los videos se suben **directo al bucket** con
una URL firmada, los videos y descargas se sirven con **URLs firmadas** de Storage, y el progreso en
vivo (SSE) se reconecta solo (EventSource) cuando la conexión llega a ese límite. La API no debe
mandar `Cache-Control: public` en sus respuestas (Hosting las guardaría en su CDN); hoy no lo hace.

## Variables

| Variable | API | Trabajador | Valor |
| --- | --- | --- | --- |
| `VEXORA_STORE` | sí | sí | `firestore` (local: `json`) |
| `VEXORA_BLOBS` | sí | sí | `gcs` (local: `local`) |
| `VEXORA_BUCKET` | sí | sí | `vexora-dev.firebasestorage.app` |
| `VEXORA_FIREBASE_PROJECT` | sí | sí | `vexora-dev` |
| `VEXORA_INPROCESS_WORKERS` | `0` | — | hilos de trabajo dentro de la API (local: 1) |
| `VEXORA_WORKERS` | — | `1` | trabajadores por proceso |
| `VEXORA_LEASE_S` | sí | sí | 60 (mismo valor en los dos) |
| `VEXORA_QUEUE_POLL_S` | — | opcional | espera entre búsquedas (5 s con Firestore: cada búsqueda vacía cuesta 1 lectura) |
| `VEXORA_FIRESTORE_PREFIX` | opcional | opcional | prefijo de colecciones por entorno |
| `VEXORA_ENV` | `prod` | `prod` | |
| `VEXORA_SECRET` | secreto | — | igual en todas las instancias |
| `VEXORA_CORS_ORIGINS` | opcional | — | con Firebase Hosting la web y la API comparten dominio: solo hace falta para llamar a la URL directa de Cloud Run desde otro origen |
| `GEMINI_API_KEY`, `OPENAI_API_KEY` | secreto | secreto | |

## Probar contra la nube desde local

```bash
VEXORA_LIVE_TESTS=1 GOOGLE_APPLICATION_CREDENTIALS=/ruta/llave.json \
VEXORA_FIREBASE_PROJECT=vexora-dev VEXORA_BUCKET=vexora-dev.firebasestorage.app \
.venv/bin/python -m pytest -q tests/test_cloud_live.py
```

Usa colecciones y objetos `_smoke_<azar>` y los borra al final. La suite normal nunca toca la nube.
Para correr todo en local con la nube: las mismas variables más `VEXORA_STORE=firestore
VEXORA_BLOBS=gcs`, `vfxglow-api` con `VEXORA_INPROCESS_WORKERS=0` y `vexora-worker` en otra terminal.
(En local, con el JSON, la API y `vexora-worker` también pueden compartir `api_data/`: el archivo
se bloquea entre procesos.)

## Limitaciones conocidas y siguientes pasos

- **Límites de las páginas públicas** (enlaces compartidos, api/ratelimit.py): 30 peticiones por
  minuto por IP a la página, 120 al video, y 10 enlaces inexistentes en 10 minutos bloquean esa IP
  15 minutos; además, cada enlace tiene un tope de vistas al día según el plan del dueño
  (`share_daily_views` en configs/plans.yaml). Se cuentan en memoria: son exactos con una sola
  instancia de la API. Con más tráfico, agregar una regla de límite por IP en Cloud Armor (requiere
  un balanceador de carga, ~18 USD/mes) para frenar el abuso antes de que llegue a la API.

- **Subidas (análisis temprano), vistas previas y capas del editor siguen en la API**, en hilos y
  con estado en memoria o en su disco. Por eso la API va con una instancia. Siguiente paso:
  llevarlas a la misma cola (tipos de trabajo) y guardar su estado en Firestore.
- **`runs/` (caché del análisis) es local de cada trabajador.** Un trabajador "frío" (otra
  instancia, o tras un reinicio) vuelve a analizar el video aunque otro ya lo hubiera hecho; la
  subida analizada en la API tampoco le sirve al trabajador. Siguiente paso: publicar el análisis
  (`analysis/`) en el bucket por hash de video.
- Por lo mismo, en la nube la API no tiene `runs/`: `/choreography`, `/people` y "Preparar para
  editar" (versiones anteriores al editor) devuelven vacío o 409. Los trabajos nuevos guardan sus
  artefactos del editor en el bucket y sí se editan.
- `runs/` del trabajador no se limpia al borrar un trabajo desde la API (otra máquina). Siguiente
  paso: una caducidad por antigüedad en el trabajador.
- Las miniaturas y la tira de fotogramas se generan y guardan en el disco de la instancia de la
  API (se regeneran si cambia la instancia).
- El autoescalado de trabajadores por profundidad de cola no existe aún.
- Prioridad: hoy todos 0; `workqueue.priority_for(owner)` es el gancho para leerla del plan.
- Firestore no admite listas dentro de listas; hoy ningún campo guardado las tiene. Si un campo
  nuevo las necesitara, hay que guardarlo como texto JSON.
- Al arrancar, la API marca como fallidas las subidas que estaban "analizando" (las de otra
  instancia también): en un despliegue con dos instancias a la vez puede cortar un análisis.

## Cola de tareas, subidas directas y caché de análisis

Con esto la API ya no guarda estado entre peticiones y puede correr con varias instancias; todo lo
pesado lo hacen trabajadores. Resuelve las limitaciones de arriba sobre subidas, vistas previas y
capas en hilos de la API, `runs/` local de cada trabajador, `/choreography`, `/people` y "Preparar
para editar" vacíos en la nube, y el corte de análisis al arrancar otra instancia.

### Subida directa al bucket

La web ya no manda el video a la API (Cloud Run corta los cuerpos a 32 MiB y Firebase Hosting las
peticiones a 60 s):

1. `POST /api/uploads` con JSON `{filename, size, content_type}`. La API valida extensión (415) y
   tamaño declarado (413) **antes** de dar nada, crea la subida en estado `uploading` y responde
   `upload: {method: "PUT", url, headers, expires}`:
   - `VEXORA_BLOBS=gcs`: URL firmada V4 de PUT a `uploads/<id>/<nombre>` del bucket, válida 15 min,
     con el `Content-Type` y `x-goog-content-length-range: 0,<tamaño declarado>` atados a la firma
     (el bucket rechaza otro tipo o más bytes).
   - `VEXORA_BLOBS=local`: `PUT /api/uploads/<id>/file?k=<llave>` de la propia API (en local se usa
     igual). La llave va ligada a la subida y a su dueño; corta si llegan más bytes de los declarados.
2. El navegador hace el PUT con esas cabeceras tal cual (XHR con progreso real, sin la sesión).
3. `POST /api/uploads/<id>/complete`: la API comprueba que el objeto existe y su tamaño real (409
   si no llegó, 413 si pasa del máximo; en ambos casos la subida queda `failed` y el objeto se
   borra) y encola el sondeo + análisis como tarea. Responde `analyzing` sin esperar. Con archivos
   locales sondea ya (422 con el motivo si el video no cabe); con el bucket sondea el trabajador
   (bajar 500 MB puede pasar de 60 s) y, si no cabe, la subida queda `failed` con el mensaje del
   sondeo (`error_code`: `invalid_video`, `too_large`, `upload_missing`) y el objeto se borra.
4. `POST /api/jobs` con `upload_id`, como antes. El video se copia dentro del bucket a
   `uploads/<trabajo>/` (copia del lado del servidor). Si la subida aún no se había sondeado, el
   trabajo lleva `probe: true` y su trabajador lo sondea antes de procesarlo.

`POST /api/uploads` con multipart (campo `video`) y `POST /api/jobs` con el archivo siguen
funcionando (pruebas, clientes viejos, local). Las subidas `uploading` sin completar se borran a la
hora (documento y objeto).

**CORS del bucket** (el PUT del navegador es de otro origen y manda cabeceras propias). Reemplaza
el `cors.json` de "Storage: CORS" por este (incluye lo de lectura):

```json
[
  {
    "origin": ["https://vexora-dev.web.app", "https://vexora-dev.firebaseapp.com", "https://<tu-dominio>", "http://localhost:5173"],
    "method": ["PUT", "GET", "HEAD"],
    "responseHeader": ["Content-Type", "x-goog-content-length-range", "Range", "Accept-Ranges", "Content-Length"],
    "maxAgeSeconds": 3600
  }
]
```

```bash
gcloud storage buckets update gs://vexora-dev.firebasestorage.app --cors-file=cors.json
```

**Ciclo de vida** (red de seguridad para subidas abandonadas que la API no alcance a borrar). Ojo:
los videos de los trabajos también viven en `uploads/<trabajo>/`; si se quiere la regla, que borre a
1 día solo las subidas tempranas, cuyo id empieza por `u_`:

```json
{ "rule": [{ "action": { "type": "Delete" }, "condition": { "age": 1, "matchesPrefix": ["uploads/u_"] } }] }
```

```bash
gcloud storage buckets update gs://vexora-dev.firebasestorage.app --lifecycle-file=lifecycle.json
```

### Tareas en la cola

Análisis de subidas, vistas previas (editor y Estudio) y capas de la vista en vivo son documentos de
la colección `tasks` (api/tasks.py) con la misma maquinaria que los trabajos (tomar en transacción,
turno con latido, 3 intentos, recuperación al vencer el turno). Prioridad, de más a menos:

| `kind` | Prioridad | Por qué |
| --- | --- | --- |
| `preview` | 30 | Segundos de render; alguien mira la pantalla esperando. Una pendiente y una dibujándose por persona. |
| `upload` | 20 | La persona elige estilo mientras tanto y el trabajo reutiliza el análisis. |
| `layers` | 10 | Opcional; ~0,1 s por fotograma. |
| trabajos (`jobs`) | 0 | Minutos; la persona ya sabe que espera. |

Los resultados viven en el almacén: estado en el documento de la tarea (las respuestas de la API
no cambian: `rendering`/`ready`/`failed`), MP4 de vistas previas en `previews/<trabajo>/<id>.mp4`,
capas en `outputs/<id>.layers.*`, cuota diaria de vistas previas en `preview_quota/<uid>`.

- En la API con `VEXORA_INPROCESS_WORKERS>0` (local): un hilo para trabajos y uno por tipo de
  tarea, como antes.
- `vexora-worker` toma todo por prioridad; `VEXORA_WORKER_KINDS=preview,upload` limita lo que toma
  un proceso (p. ej. un servicio pequeño solo para vistas previas).
- En la nube, la API va con `VEXORA_INPROCESS_WORKERS=0`.

### Caché del análisis en el bucket

Tras analizar, el trabajador publica `analysis/` (manifiesto aparte; sin `debug_overlay.mp4` ni
`scene_cache/`) en `analysis/<sha256[:16]>/<clave[:24]>/` y al final `index.json` (sin él la entrada
no existe: publicar es atómico). La clave es la de la etapa de análisis (config + huella del
código). Antes de analizar, un trabajador frío la trae y no analiza. Entre máquinas, un candado con
turno en `analysis_locks/<entrada>` evita que dos analicen el mismo video a la vez. La API trae del
bucket lo que lee: brief de la vista previa del Estudio, pistas de `/people`, análisis para
"Preparar para editar"; `/choreography` sale de `outputs/<id>.choreography.json`, que se guarda con
cada versión. Con `VEXORA_BLOBS=local` no hace nada.

### Índices de Firestore

`firestore.indexes.json` suma dos índices de `tasks` (`status, worker, priority desc, created` y
`kind, status, worker, priority desc, created`) y exenciones para `tasks.payload`, `tasks.result` y
`preview_quota.times`. Despliégalos con `firebase deploy --only firestore:indexes` antes de subir la
API nueva.

### Trabajadores bajo demanda: Cloud Run Job

Para no pagar un trabajador encendido sin trabajo:

- `vexora-worker` con `VEXORA_WORKER_IDLE_EXIT_S=60` sale (código 0) tras 60 s sin nada que tomar.
  Solo sale entre vuelta y vuelta: nunca con un turno en la mano.
- Cada trabajador deja su latido en `workers/<id>` (cada 30 s; vivo = latido de menos de 90 s).
- Al encolar cualquier cosa, la API mira si hay trabajadores vivos; si no, lanza una ejecución del
  Job (`VEXORA_WORKER_JOB`). Una transacción sobre `system/worker_wake` cuenta las ejecuciones
  lanzadas en los últimos 60 s como "arrancando": diez trabajos seguidos lanzan una sola.
  `VEXORA_WORKER_MAX_PARALLEL` (por defecto 1) permite varias si la cola es profunda. Un fallo al
  lanzar no falla la petición (registro + evento `worker.wake_failed`).

```bash
gcloud run jobs create vexora-worker --image $IMAGE --region $REGION --service-account $SA \
  --command vexora-worker --tasks 1 --max-retries 0 --task-timeout 3600 --cpu 4 --memory 8Gi \
  --set-env-vars VEXORA_ENV=prod,VEXORA_STORE=firestore,VEXORA_BLOBS=gcs,VEXORA_BUCKET=vexora-dev.firebasestorage.app,VEXORA_FIREBASE_PROJECT=$PROJECT,VEXORA_WORKERS=1,VEXORA_WORKER_IDLE_EXIT_S=60 \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest,OPENAI_API_KEY=openai-api-key:latest

# La API lo lanza: su cuenta de servicio necesita run.jobs.run sobre el Job.
gcloud run jobs add-iam-policy-binding vexora-worker --region $REGION \
  --member=serviceAccount:$SA --role=roles/run.invoker   # o roles/run.developer en el proyecto

gcloud run services update vexora-api --region $REGION \
  --update-env-vars VEXORA_INPROCESS_WORKERS=0,VEXORA_WORKER_JOB=projects/$PROJECT/locations/$REGION/jobs/vexora-worker
```

La imagen necesita el extra `[cloud]` (incluye `google-cloud-run`). Costo y espera: con todo
apagado, el primer video (o vista previa) tras un rato sin uso espera el arranque en frío del Job,
~30-60 s (imagen + modelos), antes de empezar. Si una ejecución llega a `--task-timeout` con un
trabajo a medias, su turno vence, el trabajo vuelve a la cola y la siguiente ejecución lo toma.
Mientras haya uso continuo, conviene el servicio siempre encendido de "Trabajadores" (opción A):
responde al instante. Se pueden combinar: un servicio pequeño con `VEXORA_WORKER_KINDS=preview`
siempre encendido y el Job para lo demás.

### Variables nuevas

| Variable | Dónde | Para qué |
| --- | --- | --- |
| `VEXORA_WORKER_KINDS` | worker | Qué toma: `job,preview,upload,layers` (sin valor, todo) |
| `VEXORA_WORKER_IDLE_EXIT_S` | worker | Sale tras N s sin trabajo (sin valor, nunca) |
| `VEXORA_WORKER_JOB` | API | Cloud Run Job a lanzar al encolar si no hay trabajadores vivos |
| `VEXORA_WORKER_MAX_PARALLEL` | API | Ejecuciones a la vez del Job (por defecto 1) |

### Lo que sigue pendiente

- `runs/` de cada máquina sigue sin caducidad (ahora es solo caché: se puede borrar sin perder nada
  publicado). Lo publicado en `analysis/` se borra con el último trabajo o subida del video.
- Miniaturas y tira de fotogramas se siguen generando en el disco de la instancia de la API.
- "Preparar para editar" (versiones anteriores al editor) sigue en la API y baja el video para
  calcular su hash; solo encuentra el análisis si alguna máquina lo publicó.
- Un trabajo lanzado antes de que termine el sondeo de su subida directa se sondea en el
  trabajador: un video que no cabe falla ahí (con el mensaje claro), no al crearlo.
- Los límites por IP de las páginas públicas siguen en memoria de cada instancia.
