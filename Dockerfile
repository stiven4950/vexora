# Una imagen, dos comandos (docs/despliegue_cloud_run.md):
#   API:          (por defecto) vfxglow-api en $PORT (registro JSON y la comprobación de check_bind)
#   trabajadores: vexora-worker
# Sin secretos dentro: llegan como variables desde Secret Manager al desplegar.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VFXGLOW_ROOT=/app \
    VEXORA_STORE=firestore \
    VEXORA_BLOBS=gcs \
    VEXORA_LOG_FORMAT=json

# ffmpeg para el video; libGL/EGL/GLES y glib para OpenCV y MediaPipe (sin libgles2 el análisis
# falla con "libGLESv2.so.2: cannot open shared object file"); fontconfig para Skia.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libegl1 libgles2 libglib2.0-0 libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Extras de Python. "objects" trae ultralytics (YOLO): torch se instala en su versión CPU.
ARG EXTRAS=api,cloud,objects
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu ".[${EXTRAS}]"

COPY configs ./configs
COPY assets ./assets
COPY models ./models
COPY yolo11n.pt yolo11n-obb.pt ./

# Sin root en ejecución.
RUN useradd --create-home --uid 10001 vexora \
    && mkdir -p /app/api_data /app/runs /app/logs \
    && chown -R vexora /app/api_data /app/runs /app/logs
USER vexora

ENV PORT=8080
CMD ["sh", "-c", "exec env VFXGLOW_HOST=0.0.0.0 VFXGLOW_PORT=${PORT} vfxglow-api"]
