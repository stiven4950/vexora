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
- [ ] `OPENAI_API_KEY=... GEMINI_API_KEY=... scripts/deploy_cloud.sh setup` (una vez).
- [ ] `scripts/deploy_cloud.sh all`.

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
