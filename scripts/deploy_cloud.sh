#!/usr/bin/env bash
# Despliegue de Vexora en Google Cloud (docs/despliegue_cloud_run.md):
#   API en Cloud Run (sin estado, escala a cero), trabajadores como Cloud Run Job que la API lanza al
#   encolar y que se apaga solo sin trabajo, y la web en Firebase Hosting (reenvía /api/** a la API).
#
# Uso (desde la raíz del repositorio, con gcloud y firebase con sesión iniciada):
#   scripts/deploy_cloud.sh setup    # una vez: APIs, repositorio, cuenta de servicio, secretos, bucket
#   scripts/deploy_cloud.sh build    # construye la imagen en Cloud Build y la sube
#   scripts/deploy_cloud.sh deploy   # API + Job de trabajadores + índices/reglas + web
#   scripts/deploy_cloud.sh all      # build + deploy
#
# Las claves de IA para los secretos se leen de la terminal SOLO al crear los secretos (setup):
#   META_API_KEY=... OPENAI_API_KEY=... GEMINI_API_KEY=... scripts/deploy_cloud.sh setup
# Nunca se escriben en archivos ni en la imagen. META_API_KEY es la del análisis profundo por
# defecto (Muse Spark + Muse Voice Transcribe); sin ella el análisis profundo falla.
#
# Quién puede pedir el análisis profundo (de pago) se fija al desplegar (deploy/all), no en el código:
#   VEXORA_DEEP_ALLOW="ana@correo.com,uid123" scripts/deploy_cloud.sh deploy    # "*" = todos
# Sin VEXORA_DEEP_ALLOW, nadie lo tiene. Topes: VEXORA_DAILY_DEEP (2 por usuario al día) y
# VEXORA_DAILY_DEEP_GLOBAL (20 al día entre todos), también opcionales al desplegar.
# Demo de la hackatón: abierto a toda cuenta con sesión hasta una fecha, y luego se cierra solo:
#   VEXORA_DEEP_OPEN_UNTIL=2026-11-30T23:59:00-05:00 VEXORA_DAILY_DEEP=5 VEXORA_DAILY_DEEP_GLOBAL=60 \
#     VEXORA_DEEP_ALLOW="tu@correo.com" scripts/deploy_cloud.sh deploy
set -euo pipefail

PROJECT="${PROJECT:-vexora-dev}"
REGION="${REGION:-us-east1}"
BUCKET="${BUCKET:-vexora-dev.firebasestorage.app}"
SA_NAME="${SA_NAME:-vexora-run}"
SA="$SA_NAME@$PROJECT.iam.gserviceaccount.com"
REPO="$REGION-docker.pkg.dev/$PROJECT/vexora/vexora"
IMAGE_FILE=".last-image"  # la última imagen construida (no se sube a git)

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

secret_exists() { gcloud secrets describe "$1" --project "$PROJECT" >/dev/null 2>&1; }

# Crea el secreto si no existe; el valor llega por la entrada estándar (nunca como argumento).
ensure_secret() {
  local name="$1" value="$2"
  if secret_exists "$name"; then
    echo "secreto $name: ya existe"
  elif [ -n "$value" ]; then
    printf '%s' "$value" | gcloud secrets create "$name" --project "$PROJECT" --data-file=- >/dev/null
    echo "secreto $name: creado"
  else
    echo "secreto $name: sin valor (opcional; la función que lo usa quedará apagada)"
  fi
}

setup() {
  log "APIs de Google Cloud"
  gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
    secretmanager.googleapis.com firestore.googleapis.com iamcredentials.googleapis.com --project "$PROJECT"

  log "Repositorio de imágenes"
  gcloud artifacts repositories describe vexora --location "$REGION" --project "$PROJECT" >/dev/null 2>&1 ||
    gcloud artifacts repositories create vexora --repository-format=docker --location "$REGION" --project "$PROJECT"

  log "Cuenta de servicio $SA y permisos"
  gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" --display-name "Vexora en Cloud Run"
  for role in roles/datastore.user roles/secretmanager.secretAccessor roles/run.developer; do
    gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role "$role" --condition None >/dev/null
  done
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$SA" --role roles/storage.objectAdmin >/dev/null
  # Firmar URLs del bucket sin llave privada (signBlob) y lanzar el Job con su propia identidad.
  gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT" \
    --member "serviceAccount:$SA" --role roles/iam.serviceAccountTokenCreator >/dev/null
  gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT" \
    --member "serviceAccount:$SA" --role roles/iam.serviceAccountUser >/dev/null

  log "Secretos (Secret Manager)"
  ensure_secret vexora-secret "$(secret_exists vexora-secret || openssl rand -hex 32)"
  ensure_secret meta-api-key "${META_API_KEY:-}"
  ensure_secret openai-api-key "${OPENAI_API_KEY:-}"
  ensure_secret gemini-api-key "${GEMINI_API_KEY:-}"

  log "Bucket: CORS (subida directa desde el navegador) y ciclo de vida (subidas abandonadas)"
  local tmp
  tmp="$(mktemp -d)"
  cat >"$tmp/cors.json" <<EOF
[{"origin": ["https://$PROJECT.web.app", "https://$PROJECT.firebaseapp.com", "http://localhost:5173"],
  "method": ["PUT", "GET", "HEAD"],
  "responseHeader": ["Content-Type", "x-goog-content-length-range", "Range", "Accept-Ranges", "Content-Length"],
  "maxAgeSeconds": 3600}]
EOF
  cat >"$tmp/lifecycle.json" <<'EOF'
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 1, "matchesPrefix": ["uploads/u_"]}}]}
EOF
  gcloud storage buckets update "gs://$BUCKET" --cors-file="$tmp/cors.json" --lifecycle-file="$tmp/lifecycle.json"
  rm -rf "$tmp"
  echo "Con dominio propio, agrega su origen al CORS (docs/despliegue_cloud_run.md)."
}

build() {
  local image="$REPO:$(date +%Y%m%d-%H%M)"
  log "Construyendo $image en Cloud Build"
  gcloud builds submit --project "$PROJECT" --region "$REGION" --tag "$image" .
  echo "$image" >"$IMAGE_FILE"
}

# Las variables comunes de la API y de los trabajadores.
COMMON="VEXORA_ENV=prod,VEXORA_STORE=firestore,VEXORA_BLOBS=gcs,VEXORA_BUCKET=$BUCKET,VEXORA_FIREBASE_PROJECT=$PROJECT"

# Solo los secretos que existen (las claves de IA son opcionales).
secrets_for() {
  local list=""
  for pair in "$@"; do
    secret_exists "${pair#*=}" && list="$list,${pair%%=*}=${pair#*=}:latest"
  done
  echo "${list#,}"
}

deploy() {
  [ -f "$IMAGE_FILE" ] || { echo "No hay imagen: corre primero 'scripts/deploy_cloud.sh build'." >&2; exit 1; }
  local image job
  image="$(cat "$IMAGE_FILE")"
  job="projects/$PROJECT/locations/$REGION/jobs/vexora-worker"

  log "Firestore: índices y reglas; Storage: reglas (antes que la API: la cola los necesita)"
  firebase deploy --project "$PROJECT" --only firestore:indexes,firestore:rules,storage

  log "Trabajadores: Cloud Run Job (se apaga a los 60 s sin trabajo)"
  local job_flags=(--image "$image" --region "$REGION" --project "$PROJECT" --service-account "$SA"
    --command vexora-worker --tasks 1 --max-retries 0 --task-timeout 3600 --cpu 4 --memory 8Gi
    --set-env-vars "$COMMON,VEXORA_WORKERS=1,VEXORA_WORKER_IDLE_EXIT_S=60")
  local worker_secrets
  worker_secrets="$(secrets_for META_API_KEY=meta-api-key OPENAI_API_KEY=openai-api-key GEMINI_API_KEY=gemini-api-key)"
  [ -n "$worker_secrets" ] && job_flags+=(--set-secrets "$worker_secrets")
  secret_exists meta-api-key || echo "AVISO: sin el secreto meta-api-key el análisis profundo (Muse Spark) fallará: META_API_KEY=... scripts/deploy_cloud.sh setup"
  if gcloud run jobs describe vexora-worker --region "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
    gcloud run jobs update vexora-worker "${job_flags[@]}"
  else
    gcloud run jobs create vexora-worker "${job_flags[@]}"
  fi

  log "API: Cloud Run (escala a cero; lanza el Job al encolar)"
  # La API decide quién puede pedir el análisis profundo (api/limits.py). VEXORA_DEEP_ALLOW es una
  # lista con comas, así que las variables van separadas por "|" (sintaxis ^|^ de gcloud).
  local api_env="$COMMON,VEXORA_INPROCESS_WORKERS=0,VEXORA_PROXY_HOPS=2,VEXORA_WORKER_JOB=$job"
  api_env="${api_env//,/|}|VEXORA_DEEP_ALLOW=${VEXORA_DEEP_ALLOW:-}"
  [ -n "${VEXORA_DAILY_DEEP:-}" ] && api_env="$api_env|VEXORA_DAILY_DEEP=$VEXORA_DAILY_DEEP"
  [ -n "${VEXORA_DAILY_DEEP_GLOBAL:-}" ] && api_env="$api_env|VEXORA_DAILY_DEEP_GLOBAL=$VEXORA_DAILY_DEEP_GLOBAL"
  api_env="$api_env|VEXORA_DEEP_OPEN_UNTIL=${VEXORA_DEEP_OPEN_UNTIL:-}"
  if [ -n "${VEXORA_DEEP_OPEN_UNTIL:-}" ]; then
    echo "Análisis profundo (Muse Spark) abierto a toda cuenta con sesión hasta $VEXORA_DEEP_OPEN_UNTIL (UTC si no trae zona); después, solo: ${VEXORA_DEEP_ALLOW:-nadie}"
  elif [ -n "${VEXORA_DEEP_ALLOW:-}" ]; then
    echo "Análisis profundo (Muse Spark) para: $VEXORA_DEEP_ALLOW"
  else
    echo "AVISO: VEXORA_DEEP_ALLOW y VEXORA_DEEP_OPEN_UNTIL vacíos: nadie podrá pedir el análisis profundo."
  fi
  gcloud run deploy vexora-api --image "$image" --region "$REGION" --project "$PROJECT" --service-account "$SA" \
    --allow-unauthenticated --port 8080 --cpu 1 --memory 2Gi --timeout 300 \
    --min-instances 0 --max-instances 3 \
    --set-env-vars "^|^$api_env" \
    --set-secrets "VEXORA_SECRET=vexora-secret:latest"

  log "Web: Firebase Hosting (construye web/ con web/.env.production.local)"
  [ -f web/.env.production.local ] || echo "AVISO: falta web/.env.production.local (configuración de Firebase de la web; ver web/.env.example)."
  firebase deploy --project "$PROJECT" --only hosting

  log "Listo"
  echo "Web: https://$PROJECT.web.app   ·   API: $(gcloud run services describe vexora-api --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
  echo "Primera prueba: sube un video corto y mira 'gcloud run jobs executions list --job vexora-worker --region $REGION'."
}

case "${1:-}" in
  setup) setup ;;
  build) build ;;
  deploy) deploy ;;
  all) build && deploy ;;
  *) sed -n '2,15p' "$0"; exit 1 ;;
esac
