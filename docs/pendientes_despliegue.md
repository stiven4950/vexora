# Pendientes antes de desplegar

Lista de lo que falta para el primer despliegue en Google Cloud y para abrir al público. Lo técnico
ya está en `main` (guía: [despliegue_cloud_run.md](despliegue_cloud_run.md); script:
`scripts/deploy_cloud.sh`). Marca cada punto al hacerlo.

## 1. Antes de cualquier despliegue (también la prueba privada)

- [ ] **Alertas de presupuesto** en Google Cloud: Facturación → Presupuestos y alertas (p. ej. 20 USD/mes
      con avisos al 50 %, 90 % y 100 %).
- [ ] **Límites de gasto** en las consolas de OpenAI y de Google AI (Gemini).
- [ ] `web/.env.production.local` con la configuración de Firebase de la web (ver `web/.env.example`).
- [ ] Instalar y entrar: `brew install --cask google-cloud-sdk`, `gcloud auth login`,
      `gcloud config set project vexora-dev`, `firebase login`.
- [ ] `yolo11n.pt` y `yolo11n-obb.pt` en la raíz del repo: el `Dockerfile` los copia y no están en
      git (sin ellos `gcloud builds submit` falla).
- [ ] `META_API_KEY=... OPENAI_API_KEY=... GEMINI_API_KEY=... scripts/deploy_cloud.sh setup` (una vez).
      `META_API_KEY` es la del análisis profundo por defecto (Muse Spark); sin ella, el análisis
      profundo falla en la nube.
- [ ] `VEXORA_DEEP_ALLOW="correo1,correo2" scripts/deploy_cloud.sh all`: solo esas cuentas pueden
      pedir el análisis profundo (2 por persona al día y 20 en total; se cambian con
      `VEXORA_DAILY_DEEP` y `VEXORA_DAILY_DEEP_GLOBAL`). Sin `VEXORA_DEEP_ALLOW`, nadie lo tiene.
- [ ] **Demo de la hackatón** (el jurado prueba Muse Spark directamente): abrir el análisis profundo a
      toda cuenta con sesión hasta el fin de la evaluación, con topes que acoten el gasto; se cierra
      solo en esa fecha:
      `VEXORA_DEEP_OPEN_UNTIL=2026-11-30T23:59:00-05:00 VEXORA_DAILY_DEEP=5 VEXORA_DAILY_DEEP_GLOBAL=60 VEXORA_DEEP_ALLOW="tu@correo.com" scripts/deploy_cloud.sh all`
      (pon la fecha real del fin del jurado). Para cerrarlo antes, vuelve a correr `deploy` sin
      `VEXORA_DEEP_OPEN_UNTIL`.

Notas del PC con Windows (4 nov): `py -3.12 -m venv .venv` y `pip install -e ".[dev,scene,api]"`
funcionan (mediapipe y skia-python tienen rueda para Windows); un antivirus que inspecciona HTTPS
(Norton Web/Mail Shield) rompe las llamadas de Python a Meta y OpenAI (`CERTIFICATE_VERIFY_FAILED`);
la prueba `test_cloud_ready::test_a_worker_process_registers_every_task_kind` falla en Windows sin el
modo de desarrollador (crear enlaces simbólicos, `WinError 1314`); el estilo `baile` necesita torch
(el objeto protagonista con Grounding DINO + SAM 2).

## 2. Verificar en el primer despliegue

- [ ] Recorrido completo en la nube: subir, procesar, editar, vista previa, guardar en la nube,
      compartir, borrar la cuenta. Mejor primero en un enlace de prueba:
      `firebase hosting:channel:deploy prueba --expires 7d`.
- [ ] Límite por IP de los enlaces compartidos detrás de Firebase Hosting (`VEXORA_PROXY_HOPS=2`):
      31 recargas seguidas de un enlace → la 31 da 429 solo a ti.
- [ ] Arranque en frío del trabajador (Cloud Run Job): el primer video tras un rato sin uso tarda
      ~30–60 s más; `gcloud run jobs executions list --job vexora-worker --region us-east1`.

## 3. Antes de abrir al público

- [ ] **Casilla de aceptación** de términos y tratamiento de datos (incluidos biométricos) al
      registrarse, que pide la Ley 1581, y **verificación del correo** al crear la cuenta. (Código.)
- [ ] **Textos legales**: completar los datos de la empresa ([RAZÓN SOCIAL], [NIT], [CORREO]...) en
      `web/src/legal/` y `docs/legal/`, y revisión de un abogado.
- [ ] **Firebase Authentication** (consola): contraseña mínima más fuerte, protección contra
      enumeración de correos, dominios autorizados (con dominio propio: también como
      `VITE_FIREBASE_AUTH_DOMAIN`).
- [ ] Decidir si los trabajos locales (`api_data/`) se llevan a la nube (script de migración) o la
      nube arranca vacía.

## 4. Puede esperar a después del lanzamiento

- Explorar efectos, la pestaña "Vista de efectos" del editor y el enlace "Precios" del Inicio.
- Libro de créditos y pagos (se puede lanzar solo con Free y marca de agua).
- Cloud Armor (límite por IP delante de Cloud Run) cuando haya más tráfico.
