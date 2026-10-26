# VEXORA — Conveniencia y complejidad de las mejoras propuestas + auditoría de seguridad

## Contexto

Dos modelos externos leyeron `docs/informe_producto_ux.md` y propusieron mejoras de UX y planes de
precio. Aquí se contrasta cada propuesta con el código real (`vfxglow/`) y con datos medidos, se
estima su complejidad, se corrigen las afirmaciones que no se sostienen y se añade lo que ninguno
vio: seguridad, privacidad y un bug que bloquea varias mejoras. Entregable: este análisis; al
aprobarlo se copia a `vfxglow/docs/analisis_mejoras_y_seguridad.md` (único cambio previsto).

Escala de complejidad: **S** ≤ 2 días · **M** 3–8 días · **L** > 2 semanas (una persona).

---

## 1. Datos medidos que cambian las cuentas de los dos modelos

Ambos partieron de "6 min por 28 s" (dato de `docs/pendientes.md`, que se refería **solo al render**).
Medido sobre los 85 trabajos terminados de `api_data/jobs.json` (tiempo total / duración del video):

| Caso | Segundos de proceso por segundo de video |
| --- | --- |
| Primer trabajo de un video (análisis + render), mediana | **≈ 20 s/s** (28 s → ~9,5 min) |
| Primer trabajo, peores casos | 44–70 s/s (`baile` largo, `neon_joints`) |
| "Otra versión" (análisis en caché), mediana | **≈ 11 s/s** |

Consecuencias:
- Las proyecciones de capacidad del Modelo 1 (643 h/mes para 1.000 Pro) se quedan cortas: con
  datos reales serían **~1.000–1.300 h** de un trabajador secuencial. Hay que medir en la máquina
  de producción antes de fijar cuotas.
- **El render pesa tanto como el análisis.** Rehacer una versión no tarda "segundos" (Modelo 2):
  tarda ~11× la duración del video, porque el motor dibuja todas las capas en memoria y no las
  guarda (`engine.keep_layers: false`; guardarlas cuesta ~7 MB por fotograma y efecto).

## 2. Bug que hay que arreglar antes de cualquier mejora de versiones

`pipeline.py:372-382` nombra la salida `runs/<video>-<hash>/output/<tema>[__temporada][__fuego][__rayo].mp4`.
**No incluye `take`, vestuario ni `deep`**, y la carpeta se comparte por hash del video
(`pipeline.py:130`), también entre usuarios distintos. Efecto:
- "Probar otra versión" (take 1) **sobrescribe** el MP4 de la versión 0: el trabajo anterior pasa a
  reproducir y descargar el video nuevo.
- Dos usuarios que suben el mismo archivo con el mismo estilo **se pisan el resultado**.

Sin esto arreglado, "biblioteca agrupada" y "comparar versiones lado a lado" (ambos modelos) son
imposibles. Arreglo **S**: salida por trabajo (`api_data/outputs/<job_id>.mp4` o nombre con
`take`/vestuario/`deep`/dueño), y a medio plazo `runs/<uid>/…` como ya propone
`docs/plan_cuentas_y_nube.md`.

---

## 3. Evaluación de cada propuesta

Leyenda de conveniencia: ★★★ hacer ya · ★★ siguiente fase · ★ después o con matices · ✗ no así.

### 3.1 Antes del render

| Propuesta (origen) | Veredicto | Complejidad | Detalle técnico y corrección |
| --- | --- | --- | --- |
| Vista previa corta antes del render completo (M1 #1, M2 #4) | ★★★ con otro diseño | **M** | No recortar el clip con ffmpeg (M2 "primeros 3 s"): otro hash = otro análisis que no se reutiliza, y la coreografía cambia (el cierre, los huecos y la puntuación dependen de todo el video). Además los primeros segundos suelen ser la entrada, no lo representativo. **Mejor:** analizar el video completo una vez y renderizar solo una ventana de 3–5 s a media resolución. Por defecto, el tramo con más actividad según la línea de atención (`analysis/attention.py`), editable por el usuario. Hace falta añadir un rango de fotogramas a `render`/`compose` (hoy no existe). Costo estimado: análisis completo + ~40–60 s de render. |
| Empezar el análisis al subir, mientras el usuario elige estilo (ninguno lo propuso) | ★★★ | **M** | Gana minutos sin cambiar la UI. `vfxglow analyze` ya es una etapa aparte con caché por hash. Matiz: algunos catálogos piden extras (`needs: [blades]`, `props`), que se calcularían después, solo si hacen falta. |
| Recomendación de estilo (M1 #2, M2 #7) | ★★★ | **S–M** | Hacerla **sin LLM**, con lo que el análisis ya sabe: número de personas (`analysis/cast.py`), contactos entre personas (`person_contact`, `fist_clash`), hojas (`analysis/blades.py`, modo `auto`), volteretas (`flip`/`tumble`). Mostrarla como "Recomendado" con una frase de por qué. **No ocultar** los demás estilos (M2): la detección de hojas falla ~37 % en katanas plateadas. Requiere el análisis temprano. |
| Validación del video (M1 #7, M2 #5) | ★★★ | **S** + **M** | En el navegador (S): duración, tamaño y resolución desde `<video>` antes de subir. En el servidor tras un análisis rápido (M): % de fotogramas sin pose por persona, cuerpo cortado por el borde, público, tasa de detección de hojas. Avisar sin bloquear. "Detectar multitudes en el primer fotograma antes de subir" (M2) exigiría un modelo en el navegador: no compensa. |
| Simplificar el Estudio y resumir antes de lanzar (M1 #9, M2 flujo) | ★★★ | **S** | Mover temporada, looks, vestuario y análisis a "Opciones avanzadas" plegadas. Añadir un resumen (estilo, duración, tiempo estimado, costo). El botón dice "Revelar en neón" incluso en estilos de fuego: renombrarlo. |
| Transparencia del análisis profundo (M2 #8) | ★★★ | **S** | Mientras no haya cobro: "Experimental · más lento". Con créditos: mostrar el saldo. Hoy dice "tiene costo" sin cifra. |
| Galería de ejemplos y "probar con un video de ejemplo" (M1 #4, §5) | ★★ | **S** técnica | Lo técnico es fácil: un trabajo de demostración precargado. El freno es **legal**: los videos de `glowing/data` son referencias de otros creadores. No se pueden publicar sin licencia; hay que grabar material propio o con permiso escrito. |

### 3.2 Durante la espera

| Propuesta | Veredicto | Complejidad | Detalle |
| --- | --- | --- | --- |
| Tiempo estimado (M1 #5, M2 #3) | ★★★ | **S** | La fórmula fija `duración × factor` (M2) falla: el factor varía de 3 a 70 s/s según el estilo y si el análisis ya está en caché. Mejor: mediana histórica por estilo y por "primero vs. versión", calculada de `jobs.json`, mostrada como rango. Mostrar también la posición en la cola. |
| Ocultar la consola técnica (M2 #3) | ★★★ | **S** | Dejarla tras "Ver detalles" en `components/Darkroom.tsx`. |
| Cancelar un trabajo (M1 #5) | ★★ | **S–M** | En cola: S (quitarlo de la cola). En curso: M. El pipeline corre en el mismo hilo, sin puntos de cancelación; hay que revisar una bandera entre fotogramas. |
| Avisar al terminar (M2 #6) | ★★ | **S / M** | S: notificación del navegador y título de la pestaña mientras esté abierta. M: correo transaccional. L: Web Push con service worker. Empezar por S. |
| Errores con lenguaje humano (M2 #10) | ★★★ | **S** | Hoy se muestra `TipoDeExcepción: mensaje` (`jobs.py:283`). Hay que clasificar (video ilegible, sin personas, IA saturada, interrumpido…), dar un mensaje claro con su acción y añadir un botón **Reintentar**, que hoy no existe. También cierra una fuga de información (§5). |

### 3.3 Resultado y edición

| Propuesta | Veredicto | Complejidad | Detalle |
| --- | --- | --- | --- |
| Editar la coreografía: quitar, cambiar, recolorear, mover (M1 #3, M2 #1) | ★★★ (lo más valioso) | **M** | Ya hay casi todo: `director/pins.py` fija momentos y `pin-export` convierte una coreografía en guion editable. Los pines ya aceptan `opcion`, `persona`, `seg`, `dur` y color (los usa el análisis profundo). Editar = exportar la coreografía a pines → modificar → renderizar con `solo_estos: true`. Falta: endpoint, UI en `ChoreographyPanel.tsx` y un campo de **intensidad** (no existe). |
| "Actualizar render rápido, en segundos" (M2) | ✗ tal como se describe | **L** si se intenta | Falso hoy: una edición = render completo (~11 s/s). Rehacer solo la ventana afectada y empalmar con ffmpeg es posible, pero choca con la persistencia de estelas y el cierre en estrellas, que dependen del historial. Prometer "actualización en ~1 min por cada 5 s editados" solo después de investigarlo. |
| Comparar versiones lado a lado (M1 #6) | ★★ | **M** | Requiere el arreglo del §2. `CompareViewer` ya sincroniza dos videos: se puede reutilizar con "versión A / versión B". |
| Exportación: resolución (M2 #9, M1 #8) | ★★ | **S** | Solo hacia abajo (720p) al codificar. Muchos videos de entrada son de 478×850: subirlos a 1080p no añade calidad. No prometerlo. |
| Exportación: formatos vertical, cuadrado y horizontal (M1 #8) | ★ | **M–L** | Recortar 9:16 a 1:1 corta efectos y personas. Haría falta un reencuadre que siga al protagonista. |
| ProRes 4444 "con canal alfa para editores" (M2, plan Pro) | ★ con corrección | **M** | Hoy ProRes sale ya mezclado con el original, sin alfa. Exportar solo las capas de efecto con alfa es posible (el motor produce RGBA), pero es otro modo de composición y los archivos son enormes. |
| "Copiar enlace" (M2 #9) | ★ (fase nube) | **M** | Las URLs actuales llevan una llave ligada al dueño que caduca a las 6 h (`auth.py`): no sirven para compartir. Hace falta un enlace público revocable, con su propia tabla de tokens y su diseño de seguridad. |

### 3.4 Biblioteca

| Propuesta | Veredicto | Complejidad | Detalle |
| --- | --- | --- | --- |
| Agrupar versiones por video (M1 #6, M2 #2) | ★★★ tras el §2 | **S** | Verdad que existe `parent` (`jobs.py:177`): agrupar en `Library.tsx` es S. Pero sin el arreglo del §2, todas las versiones de un grupo muestran el mismo MP4. |
| Nombrar versiones, buscar, filtrar, favoritos, colecciones | ★★ | **S–M** | Exige añadir campos al trabajo (`label`, `favorite`, `collection`) y la UI correspondiente. Conviene hacerlo junto con la migración a Firestore (plan de cuentas), no sobre `jobs.json`. |
| Borrado con papelera / deshacer | ★★ | **S** | Además, hoy el borrado **no borra el análisis ni los renders** de `runs/` (§5, crítica 4). |

### 3.5 Planes y precios (lo comercial queda a decisión del negocio; aquí solo la viabilidad técnica)

| Afirmación | Evaluación |
| --- | --- |
| Free sin APIs de pago (M2) | ✓ Correcto y barato. Hoy el plan gratuito sí tocaría APIs, porque el lector de escena (`gpt-5-mini`) y los accesorios se activan si hay clave. Hay que **apagarlos por plan** en el servidor. |
| "Previews ilimitadas de 3 s" (M2) | ✗ Cada vista previa cuesta análisis + ~40–60 s de CPU. Debe tener un tope diario. |
| Cola prioritaria / worker dedicado Pro (M2) | Requiere reemplazar la cola de un hilo (`jobs.py:252`) por una cola real (Redis + RQ/Celery) con varios workers y prioridades: **L**. M1 acierta: no anunciarlo hasta que exista. |
| "GPUs spot que bajan el render a <30 s" (M2) | ✗ El motor dibuja con Skia + NumPy en CPU. Una GPU no lo acelera sin reescribir el renderizador. Solo ayudaría a SAM 2 y al refinador. |
| Costo del análisis profundo "$0,10–$1,50" (M2) o "del orden de dólares" (M1) | No medido. El modelo configurado es "Gemini 4 Argon" con respaldo `gemini-3.8-flash`. La tarifa de "Gemini 3.7 Flash" que cita M1 no corresponde al modelo en uso. Hay que medirlo (§6). |
| Límites por duración (10 s / 15 s Free) | Viable (**S**) con `ffprobe` en el servidor (la duración no se valida hoy). Para que el usuario elija el tramo hace falta un recortador en la UI (**M**). |
| Marca de agua | **S–M**: `overlay`/`drawtext` de ffmpeg en `composite/encode.py`. Regla del plan: no guardar copia sin marca en Free. |
| Créditos, medición y topes de gasto (M1 §3) | ★★★ antes de cobrar: **M**. Es también un control de seguridad (abuso de costo, §5). |

### 3.6 Lo que ninguno de los dos modelos vio

1. El **bug de sobrescritura** del §2.
2. **Seguridad, abuso de costos y privacidad** (§5): el registro es abierto, no hay cuotas y cualquiera puede lanzar análisis profundos pagados.
3. **Derechos y datos personales**: los videos con caras (posiblemente de menores, en baile) se envían a Google y OpenAI. Hace falta consentimiento, política de privacidad real (Ley 1581 de Colombia / GDPR) y un borrado real.
4. **Analizar al subir**: la mejora con mejor relación beneficio/esfuerzo para la espera.
5. **Tiempos reales**: son ~1,5–3× peores que el dato usado por ambos.

---

## 4. Hoja de ruta recomendada

| Fase | Contenido | Complejidad total | Modelo de IA sugerido para implementarlo |
| --- | --- | --- | --- |
| **0 · Bloqueantes** | Arreglo del §2. Críticas de seguridad 1–4 (§5). Validar con `ffprobe`. Mensajes de error clasificados con Reintentar. Eventos JSON de trabajo, etapa y `llm.call` (§7). | ~1,5–2 semanas | Sonnet. Opus solo para el diseño de cuotas |
| **1 · Victorias rápidas** | Tiempo estimado y posición en la cola. Consola oculta. Estudio con opciones avanzadas plegadas y resumen. Validación de duración en el navegador. Biblioteca agrupada. Etiqueta del análisis profundo. Notificación del navegador. | ~1–1,5 semanas | Haiku para textos y UI simple; Sonnet para el resto |
| **2 · Núcleo de valor** | Análisis al subir. Recomendación de estilo sin LLM. Alertas de calidad del seguimiento. Edición de coreografía por pines. Vista previa por ventana. Comparar versiones. Cancelar. | ~4–6 semanas | Sonnet; Opus para el rango de fotogramas del motor |
| **3 · Comercial** | Cola multi-worker con prioridades. Firestore + Storage. Créditos, medición y topes. Marca de agua. Enlaces públicos revocables. Páginas legales. | > 6 semanas | Opus para la arquitectura; Sonnet para la implementación |
| Después / investigar | Re-render parcial. Reencuadre a 1:1. Exportación con alfa. Publicación directa en redes. | L | Opus (investigación) |

No recomendado: previews ilimitadas, prometer GPU < 30 s, ocultar estilos según la detección,
prometer "re-render en segundos".

---

## 5. Auditoría de seguridad (formato de `~/.cursor/rules/security-review.mdc`)

**NIVEL: ALTO** para exponerlo a internet · MEDIO en el uso local actual.

### Críticas (bloquean cualquier despliegue público)

- **[api/server.py:243-264, api/jobs.py:252] Abuso de costo y denegación de servicio.** El registro es abierto (correo sin verificación). No hay cuota, límite de frecuencia ni de duración, y `deep=true` llama a Gemini sin control. Un solo usuario puede encolar cientos de trabajos de 500 MB y bloquear la cola de un hilo o generar una factura alta de IA.
  Remediación: cuotas por usuario y tope global de gasto; `deep`, lector de escena y accesorios permitidos solo por plan en el servidor; duración y resolución máximas con `ffprobe`; límite de peticiones (proxy inverso o `slowapi`); límites de gasto también en las consolas de OpenAI y Google.
- **[api/server.py:197-202, api/auth.py:78] Adopción de trabajos por correo sin verificar.** `_adopt` entrega todos los trabajos sin dueño a quien inicie sesión con el correo de `VEXORA_LEGACY_OWNER`, sin comprobar `email_verified`. Si ese correo aún no tiene cuenta, cualquiera puede registrarlo con contraseña (`AuthContext.register`) y quedarse con esos trabajos.
  Remediación: exigir `claims["email_verified"]`; mejor aún, adoptar una sola vez por `uid` con un comando y retirar la variable.
- **[pipeline.py:130, 372-382] Integridad entre trabajos y usuarios.** Es el bug del §2: carpetas y salidas compartidas por hash del video, con nombres que no distinguen versión ni dueño.
  Remediación: salida por trabajo y `runs/<uid>/…`.
- **[api/jobs.py:207-216] Borrado incompleto (privacidad).** Borrar un trabajo elimina solo `api_data/uploads/<id>`. Quedan para siempre en `runs/` el análisis, `debug_overlay.mp4` (con los fotogramas de la persona), los renders y la lectura del análisis profundo.
  Remediación: borrar también la carpeta de `runs/` cuando ningún otro trabajo la use, y fijar una política de retención.

### Riesgos

- [api/server.py:256-259] Archivos multimedia no confiables procesados en el mismo proceso por OpenCV, ffmpeg y MediaPipe. Solo se valida la extensión, y el tamaño solo si se conoce. → Validar con `ffprobe` (contenedor, códec, duración, resolución). Ejecutar el worker en un contenedor sin privilegios, con límites de CPU, RAM y tiempo.
- [api/jobs.py:283, api/server.py:178] Se envían al cliente detalles internos: texto de la excepción, últimas 20 líneas del registro y rutas. → Códigos de error y registro solo en el servidor.
- [api/server.py:36-41] CORS fijo a localhost (correcto en desarrollo). → Configurable por entorno en producción, nunca `*`.
- [api/server.py:35, 471-483] Faltan cabeceras de seguridad (CSP, `X-Content-Type-Options`, `Referrer-Policy: no-referrer` para no filtrar la llave `?k=`, `frame-ancestors`, HSTS con HTTPS). `/docs` y `/openapi.json` están expuestos. → Añadir las cabeceras y apagar la documentación en producción.
- [api/auth.py:34] La llave de archivos vale 6 h y no es revocable. Es aceptable por ahora; acortarla para SSE y rotar `VEXORA_SECRET`.
- [director/deep.py, analysis/scene_reader.py, analysis/accessories.py] Videos y fotogramas con caras se envían a terceros (Gemini Files API, OpenAI). → Consentimiento explícito, política de privacidad, acuerdos de tratamiento de datos y opción de no enviarlos. La inyección de instrucciones por el audio o la imagen tiene impacto limitado porque la respuesta se valida contra el catálogo y los SVG del director se restringen. Hay que mantener esa invariante en todo lo nuevo.
- [web: dependencias] `npm audit`: 4 altas transitivas (`@grpc/grpc-js` vía `firebase` → `@firestore`). La web solo usa Auth, así que la exposición real es baja. → Actualizar `firebase` cuando haya parche. En Python no hay auditoría: correr `pip-audit`; `mediapipe <0.11` está fijado a una serie vieja.
- [Firebase] La contraseña mínima es de 6 caracteres y no se verifica el correo. → Política de contraseñas más fuerte, verificación de correo, App Check y protección contra enumeración de correos.
- [models/*.pt] Los pesos de PyTorch se cargan con pickle. → Fijar hashes de los modelos descargados.
- [.env] Las claves (OpenAI, Gemini, `VEXORA_SECRET`) solo están en `.env` local: está en `.gitignore` y **nunca se ha subido** (verificado en el historial de git). → En producción, gestor de secretos, claves separadas por entorno y rotación.

### Lo que está bien (conservar)

IDOR cubierto: `_job()` responde 404 si el trabajo es de otro usuario, y la llave de archivos va
firmada con HMAC y ligada al trabajo y al dueño. El nombre del archivo subido se sanea
(`jobs.py:166`). La ruta de la SPA impide salir de su carpeta (`server.py:480-481`). El token de
Google nunca va en una URL. `VEXORA_AUTH=off` se niega a escuchar fuera de 127.0.0.1. No hay
`innerHTML` en la web.

---

## 6. Trabajar con modelos más económicos (requisito transversal)

**En el producto (costo por video):**
- Configuración de modelo **por tarea y por nivel** en `configs/default.yaml` (`economico | estandar | premium`), con el más barato por defecto. Hoy cada tarea fija su modelo: escena `gpt-5-mini`, director `gpt-5`, análisis profundo Argon con respaldo flash.
- Ofrecer un "profundo ligero" que use directamente el modelo flash como nivel intermedio.
- Hacer **sin LLM** todo lo nuevo que se pueda: recomendación de estilo, alertas de calidad y tiempo estimado salen del análisis local.
- Mantener y ampliar las cachés por clave de prompt (`director_cache`, `deep_cache`) y el presupuesto de fotogramas adaptativo (`frame_budget: 450`).
- Registrar tokens y costo **por trabajo** en el registro del trabajo. `providers.py` ya imprime los tokens: hay que guardarlos para medir y cobrar.

**En el desarrollo (tokens de Claude Code):**
- Asignar el modelo por tarea: **Haiku** para textos, estilos, UI simple y pruebas mecánicas; **Sonnet** para la mayoría de las funciones; **Opus** solo para arquitectura (cola multi-worker, rango de fotogramas del motor, diseño de cuotas y seguridad).
- Usar `graphify query` antes de leer archivos completos, como pide `vfxglow/CLAUDE.md`.
- Mantener las tareas pequeñas y con criterio de verificación cerrado.

---

## 7. Trazabilidad y observabilidad (JSON → Grafana, después Datadog)

### Punto de partida (verificado en el código)

- El registro es texto plano (`logging.basicConfig` en `api/server.py:492`). El progreso de la web
  se **deduce con expresiones regulares** sobre esos mensajes (`api/jobs.py:70-104`, `_Progress`):
  cambiar un texto de log rompe la barra de progreso.
- Cada trabajo guarda `created`, `started` y `finished`, pero no cuánto esperó en cola ni cuánto
  tardó cada etapa.
- El pipeline ya tiene cuatro etapas delimitadas con su clave de caché: `analyze`, `direct`,
  `render` y `compose` (`pipeline.py:213-448`, método `_mark`). Es el lugar natural para medir.
- Los tokens se imprimen como texto en `director/providers.py:104-146` y
  `analysis/scene_reader.py:80`. **`director/deep.py` (Gemini, la llamada más cara) no registra
  tokens ni costo.**
- No hay identificador de correlación entre la petición HTTP, el trabajo y las llamadas a IA.

### Diseño recomendado

Neutral respecto al proveedor, para que Grafana primero y Datadog después lean lo mismo **sin
cambiar el código**: eventos JSON en una línea, nombres compatibles con OpenTelemetry y con los
atributos reservados de Datadog.

**1. Eventos JSON estructurados (base de todo).** Un `JsonFormatter` propio con la librería
estándar (sin dependencia nueva), que escriba a stdout y a `logs/events.jsonl` con rotación.
Campos comunes de cada línea:

```json
{
  "timestamp": "2026-10-23T18:04:12.345Z",
  "level": "info",
  "service": "vexora-worker",
  "env": "prod",
  "version": "1.0.0",
  "event": "stage.finished",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "job_id": "a1b2c3d4e5",
  "parent_job_id": null,
  "usr": {"id": "sha256:9f2c…"},
  "stage": "render",
  "duration_ms": 184230,
  "cache_hit": false,
  "outcome": "ok"
}
```

**2. Catálogo de eventos**, cada uno con hora de inicio y fin en UTC con milisegundos:

| Evento | Campos propios |
| --- | --- |
| `http.request` | método, ruta **plantilla** (`/api/jobs/{id}`), estado, `duration_ms`, bytes de entrada y salida, IP truncada, user-agent. Se omite la llave `?k=` |
| `upload.received` | bytes, extensión, tiempo de subida, y luego duración, fps, resolución y códec (`ffprobe`) |
| `job.created` / `job.queued` / `job.started` | estilo, tipo, `take`, temporada, looks, vestuario, `deep`, `queue_depth`, `queue_wait_ms` |
| `stage.started` / `stage.finished` | `analyze`, `direct`, `deep`, `render`, `compose`: `duration_ms`, `cache_hit`, fotogramas, fps de proceso, tiempo de CPU, pico de memoria (RSS) |
| `llm.call` | proveedor, modelo, **nivel** (`economico`/`estandar`/`premium`), tokens de entrada y salida, imágenes o segundos de video enviados, `cache_hit`, reintentos, `fallback_used`, latencia, `cost_usd_est` (tabla de precios en la configuración) |
| `job.finished` / `job.failed` / `job.cancelled` | duración total, segundos de proceso por segundo de video, tamaño del MP4, número de efectos, `error.code` clasificado (§3.2), costo total estimado |
| `user.action` | descarga, otra versión, edición de un efecto, borrado, vista previa: el embudo de UX (§3 de los modelos) |
| `security.*` | `auth.failed`, `quota.exceeded`, `rate_limited`, `media_key.invalid` |

**3. Métricas agregadas** en un endpoint `/metrics` (formato Prometheus/OpenMetrics: Grafana lo
lee directo y el Agent de Datadog también). Ejemplos: `vexora_jobs_total{style,status,deep}`,
`vexora_job_duration_seconds` y `vexora_stage_duration_seconds{stage,cache_hit}` como histogramas,
`vexora_queue_depth`, `vexora_llm_tokens_total{model,tier,direction}`,
`vexora_llm_cost_usd_total{model}`, `vexora_http_requests_total{route,status}`.

**4. Trazas (fase siguiente).** OpenTelemetry SDK, con un span por petición, trabajo, etapa y
llamada a IA, unidos por `trace_id` (se propaga de la API al worker en el registro del trabajo).
Un OpenTelemetry Collector envía a Grafana (Loki para logs, Prometheus o Mimir para métricas,
Tempo para trazas). Pasar a Datadog = añadir su exportador en el collector o instalar el Agent,
sin tocar la aplicación.

**5. Resumen por trabajo.** Los mismos datos se guardan en un campo `metrics` del trabajo
(tiempos por etapa, tokens, costo). Así sirven también a la web (tiempo estimado, §3.2) y a los
créditos (§3.5), y el progreso deja de depender de expresiones regulares sobre el texto.

### Privacidad y seguridad de la telemetría

Nunca registrar correos, tokens, llaves `?k=`, claves de API, prompts completos ni respuestas
de la IA con datos personales. El usuario va como **hash del uid** y el nombre del archivo solo
como extensión. Fijar un tiempo de retención de logs. Los eventos `security.*` alimentan alertas
(picos de 401, cuotas excedidas, gasto de IA por hora).

### Ahorro de modelos gracias a la trazabilidad

Con `llm.call` por modelo y nivel se puede comparar costo y calidad. Por ejemplo, cuántas veces
el modelo flash resolvió sin pasar al premium, o qué porcentaje de llamadas se sirve desde caché.
Con eso se decide con datos qué tarea puede bajar a un modelo más barato.

### Complejidad y orden

| Paso | Complejidad | Modelo sugerido para implementarlo |
| --- | --- | --- |
| Formateador JSON + eventos de trabajo y etapa + `trace_id` + resumen `metrics` en el trabajo | **S–M** (3–5 días) | Sonnet |
| `llm.call` con tokens y costo (incluido `deep.py`) + tabla de precios por modelo | **S** | Sonnet; Haiku para la tabla |
| Middleware `http.request` con redacción de llaves + eventos `security.*` | **S** | Sonnet |
| `/metrics` (Prometheus) + tableros de Grafana (JSON de tablero) | **M** | Sonnet para métricas; Haiku para los tableros |
| OpenTelemetry + Collector → Grafana Tempo/Loki, luego Datadog | **M** | Opus para el diseño; Sonnet para implementarlo |

Va en la **Fase 0** (eventos JSON y `llm.call`) porque es requisito para medir tiempos reales,
fijar cuotas y precios, y detectar abusos. `/metrics` y las trazas van en la Fase 1–2.

---

## 8. Verificación de este análisis

- Tiempos: rehacer la medición sobre `api_data/jobs.json` (ya hecha: 85 trabajos) y, antes de fijar precios, en la máquina de producción.
- Bug del §2: reproducirlo con dos "Probar otra versión" del mismo estilo y comprobar que el primer trabajo cambia de video. Tras el arreglo, añadir una prueba en `tests/test_api.py`.
- Seguridad: pruebas de API para 404 entre usuarios, rechazo de un correo sin verificar en la adopción, cuota excedida → 429, video demasiado largo → 413/422 y borrado que limpia `runs/`. Además, `pip-audit` y `npm audit`.
- Trazabilidad: correr un trabajo y una versión. Validar que cada línea de `logs/events.jsonl` sea JSON válido (`jq`). Comprobar que haya `stage.started`/`stage.finished` por etapa con `duration_ms` que sumen ≈ la duración total, y que `llm.call` traiga los tokens. Buscar con `grep` que no aparezcan correos ni `?k=`. Comprobar que `/metrics` responde y que Grafana local (docker compose con Loki + Prometheus) muestra el tablero.
- Al aprobar: copiar este documento a `vfxglow/docs/analisis_mejoras_y_seguridad.md`.
