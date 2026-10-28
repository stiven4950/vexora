# Despliegue en Google Cloud Run (API + trabajadores) con Firestore y Firebase Storage

La web va a Vercel; la API de Python y los trabajadores, a Cloud Run, en el mismo proyecto de
Google Cloud que Firebase (`VEXORA_FIREBASE_PROJECT`, hoy `vexora-dev`). Región recomendada:
**us-east1**, la misma del bucket (`vexora-dev.firebasestorage.app`), para no pagar tráfico entre
regiones ni sumar latencia al subir y bajar videos.

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
  --set-env-vars VEXORA_ENV=prod,VEXORA_STORE=firestore,VEXORA_BLOBS=gcs,VEXORA_BUCKET=vexora-dev.firebasestorage.app,VEXORA_FIREBASE_PROJECT=$PROJECT,VEXORA_INPROCESS_WORKERS=0,VEXORA_PROXY_HOPS=1,VEXORA_CORS_ORIGINS=https://<tu-dominio-de-vercel> \
  --set-secrets VEXORA_SECRET=vexora-secret:latest,GEMINI_API_KEY=gemini-api-key:latest
```

- `VEXORA_INPROCESS_WORKERS=0`: la API no procesa trabajos (lo hacen los trabajadores).
- `VEXORA_PROXY_HOPS=1`: Cloud Run agrega la IP real al final de `X-Forwarded-For`; los límites de
  las páginas públicas (api/ratelimit.py) usan esa, no las que puede inventar el cliente. Con un
  balanceador de carga delante son 2.
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
[{ "origin": ["https://<tu-dominio-de-vercel>", "http://localhost:5173"], "method": ["GET", "HEAD"], "responseHeader": ["Content-Type", "Range", "Accept-Ranges", "Content-Length"], "maxAgeSeconds": 3600 }]
```

```bash
gcloud storage buckets update gs://vexora-dev.firebasestorage.app --cors-file=cors.json
```

Y en ese caso los elementos que leen píxeles llevan `crossOrigin="anonymous"`.

## Vercel

El front pide `/api/...` a su mismo dominio. En Vercel, una reescritura lo manda a la API de Cloud
Run (archivo `web/vercel.json`, que se crea del lado de la web):

```json
{ "rewrites": [{ "source": "/api/(.*)", "destination": "https://vexora-api-<hash>-ue.a.run.app/api/$1" }] }
```

Notas: el proxy de Vercel puede imponer límites de tamaño de cuerpo y de duración (compruébalos
en su documentación para tu plan), así que las **subidas de video** y el **SSE** conviene
mandarlos directo a la URL de Cloud Run (con `VEXORA_CORS_ORIGINS` puesto al dominio de Vercel),
y la reescritura para el resto. Las redirecciones 307 a URLs firmadas del bucket funcionan igual a
través del proxy.

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
| `VEXORA_CORS_ORIGINS` | sí | — | dominio de Vercel |
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
