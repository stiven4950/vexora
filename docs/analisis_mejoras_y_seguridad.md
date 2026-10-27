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
| **0 · Bloqueantes** ✅ hecha | Arreglo del §2. Críticas de seguridad 1–4 (§5). Validar con `ffprobe`. Mensajes de error clasificados con Reintentar. Eventos JSON de trabajo, etapa y `llm.call` (§7). | ~1,5–2 semanas | Sonnet. Opus solo para el diseño de cuotas |
| **1 · Victorias rápidas** ✅ hecha | Tiempo estimado y posición en la cola. Consola oculta. Estudio con opciones avanzadas plegadas y resumen. Validación de duración en el navegador. Biblioteca agrupada. Etiqueta del análisis profundo. Notificación del navegador. | ~1–1,5 semanas | Haiku para textos y UI simple; Sonnet para el resto |
| **1b · Vistas base** (§9) ✅ hecha (shell, Mis proyectos, Trabajo en proceso, Estudio, Inicio, acceso en rutas, configuración mínima, catálogos por elemento; faltan los textos legales y el material real de demostración) | Rediseño fiel a los diseños: shell de la app y rutas `/app/*`. Mis proyectos, Trabajo en proceso, Estudio (vuelve a los pasos visibles del diseño), Inicio público, acceso en rutas, legales y configuración mínima. Backend S de cada vista: `title`, actividad, tiempos por etapa en vivo, ficha del video y cancelar. | ~3–4 semanas | Opus para el shell y las rutas; Sonnet para las vistas; Haiku para iconos y textos |
| **2 · Núcleo de valor** ✅ hecha salvo Explorar efectos | ✅ **Editor de efectos (§9.5 E)**: pistas por efecto, quitar, mover, agregar, color, intensidad, tamaño, render parcial y "Preparar para editar". ✅ Análisis al subir y recomendación de estilo sin LLM ("Sorpréndeme"). ✅ Alertas de calidad del seguimiento. ✅ Vista previa rápida en el editor (§10.4, ~10–20 s, dibujada a 640 px). ✅ Vista previa "Con efectos" en el Estudio (3 s del tramo más activo, ~5–15 s a 480 px; Espadas y Baile buscan las hojas o la gorra solo en ese tramo: ~20 s y ~60 s). ✅ Versiones del proyecto y comparar A/B. Pendiente: capas en el navegador (§10.3) y Explorar efectos (falta material de demostración propio). | ~5–7 semanas | Sonnet; Opus para el rango de fotogramas del motor y el editor |
| **3 · Comercial** | Cola multi-worker con prioridades. Firestore + Storage. Créditos, medición y topes. Marca de agua. Enlaces públicos revocables ("Compartir"). Vistas Mi plan / Consumo, configuración completa y campana de notificaciones (§9.6). | > 6 semanas | Opus para la arquitectura; Sonnet para la implementación |
| Después / investigar | ~~Re-render parcial~~ (hecho con el editor). Reencuadre a 1:1. Exportación con alfa. Publicación directa en redes. | L | Opus (investigación) |

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

---

## 9. Vistas de la web y diseños de referencia

### 9.1 Estado y origen

- **Ya hecho y subido** (rama `feature/SRR-phase0-security-and-tracing`): toda la Fase 0 y la parte de
  la Fase 1 que no depende del rediseño. Eso incluye el tiempo estimado y la posición en la cola,
  la consola plegada, los avisos de límites, la Biblioteca agrupada por versiones, las
  notificaciones y `/api/limits`.
- **Hoy hay 3 rutas** (`web/src/App.tsx`): `/` Estudio, `/jobs/:id` Trabajo y `/library` Biblioteca.
  El login no es una ruta: se muestra cuando no hay sesión.
- **Propuesta de vistas:** viene de ChatGPT y la adopto con los ajustes de §9.4. Se suman los
  **5 diseños** que entregó el usuario. Esos diseños son la referencia visual obligatoria y el
  resultado debe quedar **fiel**: misma estructura, jerarquía, espaciado, colores, tipografía e
  iconografía.

### 9.2 Imágenes de referencia (paso 0 de la implementación)

Las imágenes están en una carpeta temporal que el sistema puede borrar:
`/private/tmp/claude-502/-Users-omarrivera-Documents-IA/6a636f2f-00ec-4ca4-aada-4145f3c49a54/images/`.
Al aprobar, lo primero es **copiarlas al repositorio** con nombre de vista y versionarlas:

| Archivo temporal | Copia en el repo | Vista |
| --- | --- | --- |
| `1.png` | `docs/disenos/editor-efectos.png` | Editor de efectos (`/app/projects/:id/edit`) |
| `2.png` | `docs/disenos/estudio.png` | Estudio (`/app/studio`) |
| `3.png` | `docs/disenos/landing.png` | Inicio público (`/`) |
| `4.png` | `docs/disenos/mis-proyectos.png` | Mis proyectos (`/app/library`) |
| `5.png` | `docs/disenos/procesando.png` | Trabajo en proceso (`/app/jobs/:id`, estado en curso) |

`docs/disenos/README.md` lista cada imagen con su ruta y su fase. Las descripciones de §9.5 dejan
el diseño documentado aunque las imágenes se pierdan.

### 9.3 Sistema visual común (sale de los 5 diseños)

- **Paleta y tipografía:** ya existen en `web/src/styles/global.css` y en `index.html` (Obsidian
  `--ink`, Electric Cyan, Neural Violet, Plasma Pink; Michroma para la marca, Sora, Inter, JetBrains
  Mono). Los diseños usan esa misma paleta: se reutiliza, no se crea otra.
- **Barra superior de la app** (diseños 1, 2, 4, 5):
  - Logo VEXORA con su isotipo en "Y" cian.
  - Pestañas "Estudio · Mis proyectos · Explorar efectos · Mi plan"; la activa va subrayada en cian.
  - A la derecha, campana de notificaciones, avatar, nombre y menú desplegable.
  - Reemplaza la barra actual de `components/Shell.tsx`.
- **Barra lateral, dos variantes:**
  - **App:** Inicio, Estudio, Mis proyectos, Explorar efectos, Mi plan y Configuración, cada uno
    con icono y con el activo en una píldora cian brillante. Abajo, una tarjeta promocional con
    imagen, título, texto y botón con borde ("Ver más ejemplos" / "Ir al estudio").
  - **Proyecto** (diseños 1 y 5): "← Volver a mis proyectos", miniatura con título editable (✎) y
    fecha, y el menú del proyecto: Resumen, Editar efectos, Versiones, Procesando, Resultado y
    Descargar.
- **Componentes compartidos nuevos:**
  - `AppShell`, `ProjectSidebar`, `Card` (panel con borde de 1 px y radio de 18 px), `Segmented`
    (Original / Con efectos), `Stepper`, `StatusBadge`, `KeyValueList` (filas "Estilo … Avatar").
  - `ActivityTimeline`, `Toggle`, `ColorDot`, `Pagination`, `SearchInput` y `FilterChips` con
    contador.
  - Los que ya existen se reutilizan: `CompareViewer` (cortina antes/después y sincronía de dos
    videos), `Darkroom` (anillo de progreso), `ChoreographyPanel` (momentos), `Dropzone`,
    `StyleCard`, `NeonPreview` e `Icon`.
- **Iconos de línea con brillo:** con el estilo de `pages/Login.tsx`. Se amplía el set de
  `components/Icon.tsx` con agua, viento, rayo, fuego, rocas, campana, carpeta, tarjeta, engranaje,
  cerebro, nube, lupa, filtro, compartir y menú (⋮).
- **Breakpoints:** 1536 px, que es el tamaño de los diseños de app. Por debajo de 1280 px la
  columna derecha baja; por debajo de 760 px la barra lateral se vuelve un menú. Los diseños solo
  muestran escritorio; el móvil se resuelve con el mismo sistema.

### 9.4 Mapa de rutas (propuesta de ChatGPT, ajustada al código)

| Ruta | Vista | Fase | Diseño |
| --- | --- | --- | --- |
| `/` | Inicio público (landing) | 1b | ✅ `landing.png` |
| `/login`, `/register`, `/forgot-password` | Acceso (hoy, modos dentro de `Login.tsx`: se separan en rutas, mismo diseño actual) | 1b | Existente |
| `/reset-password` | Acción de Firebase (nueva contraseña) | 1b | Sin diseño: se usa el de Login |
| `/terms`, `/privacy`, `/support` | Legales y ayuda | 1b (el **texto** lo redacta el negocio) | Sin diseño: plantilla de documento |
| `/app/studio` | Estudio | 1b | ✅ `estudio.png` |
| `/app/jobs/:jobId` | Trabajo: cola, proceso, resultado o error (una sola vista, según estado) | 1b | ✅ `procesando.png` (en curso); el resultado reutiliza el editor sin edición |
| `/app/library` | Mis proyectos | 1b | ✅ `mis-proyectos.png` |
| `/app/projects/:projectId` (+ `/edit`, `/versions`) | Proyecto: resumen, editor, versiones | 2 | ✅ `editor-efectos.png` |
| `/app/explore` | Explorar efectos | 2 | Sin diseño |
| `/app/plan`, `/app/usage` | Plan y consumo | 3 | Sin diseño |
| `/app/settings/profile`, `/app/settings/security` | Cuenta | 3 (una mínima en 1b: perfil y cerrar sesión) | Sin diseño |

Ajustes respecto a la propuesta de ChatGPT:
- **"Proyecto" = un video y todas sus versiones.** `projectId` es el id del trabajo raíz (el que no
  tiene `parent`), así que no hace falta una entidad nueva hasta migrar a Firestore.
  `groupVersions` (`web/src/api/format.ts`) ya agrupa así.
- **Las rutas viejas redirigen:** `/jobs/:id` → `/app/jobs/:id` y `/library` → `/app/library`.
  Así no se rompen los enlaces ni las notificaciones ya enviadas.
- **El usuario con sesión** que abre `/` va directo a `/app/studio`, salvo con `?inicio=1`.
- **Las vistas sin diseño** (Explorar, Plan, Configuración, legales) no se inventan libremente:
  usan el sistema común de §9.3 y se pide su diseño antes de su fase.

### 9.5 Especificación de cada vista con diseño

#### A. Inicio público — `landing.png` · Fase 1b · M

- **Contenido:**
  - Cabecera con Cómo funciona · Estilos · Ejemplos · Precios · Ayuda, y los botones "Iniciar
    sesión" (borde) y "Crear mi primer efecto" (cian).
  - Héroe: la antetítulo "TU VIDEO, OTRO MUNDO", el título "Convierte tus videos en experiencias
    visuales **extraordinarias**", un texto, el CTA y "▶ Ver ejemplos", y a la derecha un
    comparador Original / Con efectos Vexora con su tirador.
  - Cuatro beneficios: Efectos únicos, Inteligencia artificial, Rápido y fácil, Comparte y
    sorprende.
  - "ESTILOS DESTACADOS — Efectos para cada historia": 5 tarjetas con imagen y "Ver todos los
    estilos →".
  - Banda de testimonios con un teléfono antes/después; CTA final "¿Listo para crear algo
    increíble?"; pie con redes y legales.
- **Reutiliza:** la cortina de `CompareViewer` con un video de demostración real; el resto es
  marcado y CSS.
- **Correcciones obligatorias** (fidelidad sí; contenido falso no):
  - **Testimonios:** "Sofía M.", "Carlos T." y "Daniel R." con 5 estrellas no se publican si no
    son reales. Hasta tener testimonios con permiso, el bloque conserva su composición (teléfono
    antes/después + cita) y muestra un caso real de uso del producto.
  - **Imágenes:** las de los diseños son ilustraciones. Se reemplazan por fotogramas y videos
    **renderizados por Vexora** con material propio o con licencia (§3.1: los videos de
    `glowing/data` son de otros creadores).
  - **Tarjetas de estilo:** Naturaleza, Elementos, Fantasía, Ciencia ficción y Arte visual no
    existen como estilos. Las tarjetas muestran los catálogos reales (Avatar, Baile, Pelea,
    Espadas) con la misma composición, mapeados según §9.7 (decisión 3).
  - **"Precios":** enlace con datos fijos `PENDIENTE(fase 3)` hasta que exista `/app/plan`.
- **Datos:** `/api/styles` (ya existe) para las tarjetas.

#### B. Estudio — `estudio.png` · Fase 1b · M (cambia lo hecho en la Fase 1)

- **Columna principal**, con pasos numerados en círculos cian, **todos visibles**. Esto reemplaza
  las "Opciones avanzadas" plegadas que se hicieron en la Fase 1, para ser fiel al diseño.
  1. **El plano:** formatos y máximo con el dato de `/api/limits`. Dos columnas: la zona de
     arrastre (botón "Seleccionar archivo") y la vista del video con nombre, resolución,
     duración, peso, papelera y "Cambiar".
  2. **El estilo:** chips de filtro (Todos · Avatar · Fuego · Agua · Rayo · Tierra · Viento ·
     Otros), botón "✦ Sorpréndeme con IA" y tarjetas con imagen, título, subtítulo, etiquetas y
     marca de selección.
  3. **Toque de temporada (opcional):** tarjetas con icono, nombre, colores e insignia "De
     temporada".
  4. **Fuego y rayo (solo si el estilo lo requiere):** dos grupos, "Look del fuego" y "Look del
     rayo", con tarjetas-icono de cada look.
  5. **Vestuario (solo catálogos):** fila compacta con la insignia "Opcional" que se despliega.
  6. **Análisis:** dos tarjetas, "⚡ Económico — reacciona a cada gesto" y "🧠 Profundo con IA
     **+$** — ve el video completo…".
- **Columna derecha fija:**
  - **Vista previa** con Original / Con efectos y reproductor.
  - **Información del video** (duración, resolución, tamaño).
  - **Resumen del proyecto:** miniatura, "Avatar · Mixto", insignia Económico y lista con ✓ (video
    cargado, estilo, temporada, vestuario, análisis).
  - **CTA** "Crear mis efectos →" (decisión §9.7), "Tiempo estimado: 6 min" y "⓵ 1 crédito".
- **Lo que ya existe y se reutiliza:** límites, avisos de duración y tamaño (`Dropzone.problems`),
  tiempo estimado (`approx`), temporadas, looks, vestuario, el análisis profundo cerrado según la
  cuenta, y `askPermission`.
- **Lo que falta** (se construye ya con datos fijos `PENDIENTE` según §9.7, salvo lo marcado como
  real):
  - **Imágenes por estilo** (S, real): un fotograma de demostración por catálogo, servido por
    `/api/styles`.
  - **Imagen por look de fuego o rayo** (S, real): render de muestra con el motor.
  - **Filtros por elemento** (real): los catálogos elementales de §9.7 (decisión 3).
  - **"Con efectos" en la vista previa** (fijo hasta la Fase 2): la vista previa por ventana de
    §3.1. Mientras tanto muestra un fotograma de demostración del estilo elegido, marcado
    `PENDIENTE(fase 2)`.
  - **"✦ Sorpréndeme con IA"** (fijo hasta la Fase 2): elige el primer estilo recomendado de una
    lista fija `PENDIENTE(fase 2)`. La recomendación real (§3.1) requiere analizar al subir.
  - **"1 crédito"** (fijo hasta la Fase 3): créditos.

#### C. Trabajo en proceso — `procesando.png` · Fase 1b · M

- **Encabezado** con imagen: "Tu video ya está **en proceso**" y un texto.
- **Paso a paso horizontal** de 4 etapas, cada una con icono, título, descripción y estado
  ("00:45 · Completado" / "En proceso…" / "Pendiente"): 1 Análisis del video, 2 IA y coreografía,
  3 Renderizado, 4 Finalización.
- **Bloque de avance:**
  - Anillo con "42 % Proceso general" (el de `Darkroom`).
  - Tarjeta de la etapa actual con icono, título, descripción, barra y "02:16 / 05:12"
    (transcurrido / estimado).
- **"Detalle del proceso":** tabla con Carga y preparación del video, Análisis de movimiento,
  Selección de estilo y coreografía, Renderizado de efectos y Compresión y almacenamiento. Cada
  fila lleva estado (✓ Completado / ◯ En proceso / Pendiente) y duración.
- **"Actividad reciente":** línea de tiempo con hora y evento (Video recibido, Inicio del
  procesamiento, Análisis de movimiento…).
- **Aviso:** "💡 Puedes salir de esta página. Te notificaremos cuando esté listo", más el botón
  rojo con borde "Cancelar procesamiento".
- **Columna derecha:**
  - Vista previa (baja resolución) con ▶.
  - Ficha del proyecto: título editable, archivo, resolución, duración y tamaño.
  - **Configuración aplicada:** Estilo, Temporada, Fuego y rayo, Vestuario, Análisis.
  - **Actividad reciente.** El diseño la repite en dos paneles: se deja **una sola**, en la
    columna derecha, para no duplicar.
- **Lo que ya existe:** etapas y avance (SSE `useJob`), `estimate_s`, `queue_ahead`, `waitNote`,
  notificación del navegador, eventos `stage.started/finished` con duración (telemetry).
- **Backend que falta** (S cada uno):
  1. **Tiempos por etapa en vivo:** guardar en `job.metrics` cada etapa al terminar su tramo
     (hoy solo se guarda al final del trabajo).
  2. **Actividad:** lista corta por trabajo (`job.activity`: hora y texto) que se llena con
     `job.queued`, `job.started` y `stage.*`.
  3. **Ficha del video:** guardar ancho, alto y peso del archivo (`VideoInfo` ya los mide) y un
     `title` editable (`PATCH /api/jobs/{id}`).
  4. **Cancelar** (S–M, §3.2): en cola se saca de la cola; en curso, una bandera revisada entre
     fotogramas.
- **Correcciones:**
  - La etapa 4 "Finalización / Compresión y almacenamiento" corresponde a la escritura de ffmpeg,
    que está dentro de `compose`. Se muestra con su propio tramo midiendo `encoder.close()`.
  - La "Vista previa (baja resolución)" usa la miniatura del original hasta que exista la vista
    previa con efectos.
- **Resultado y error:** es la misma ruta. Al terminar muestra la vista del editor (diseño 1) en
  solo lectura (comparador, línea de tiempo y descarga) hasta la Fase 2. El error usa el mismo
  marco con el mensaje claro y "Reintentar" (ya hechos).

#### D. Mis proyectos — `mis-proyectos.png` · Fase 1b · M

- **Encabezado:** "Mis **proyectos**" con su texto, buscador ("Buscar por nombre, estilo o
  fecha…"), filtro "Todos los estados" y "+ Crear nuevo".
- **Chips con contador:** Todos (12) · ● Completados · ● En proceso · ● Error.
- **Cuadrícula de 4 columnas.** Cada tarjeta lleva:
  - Miniatura con ▶ y la duración, más una insignia de estado (Completado verde / En proceso azul
    / Error rojo).
  - Título y etiquetas (estilo y elementos).
  - Fecha y hora, insignia de resolución (1080p / 720p), descarga ⤓ y menú ⋮ (renombrar, ver
    versiones, borrar). En error, ↻ reintentar.
- **Pie:** "Mostrando 12 de 12 proyectos", paginación y "12 / página". Tarjeta promocional en la
  barra lateral.
- **Lo que ya existe:** agrupación por proyecto (`groupVersions`), estados, reintentar, borrado,
  miniaturas.
- **Lo que falta:** `title` (de C), resolución y duración guardadas, etiquetas desde
  `style.tags` y las temporadas, y descarga directa desde la tarjeta (`output_url` ya existe). La
  búsqueda, los filtros y la paginación van en el cliente mientras los datos sean `jobs.json` (S);
  en el servidor cuando se migre a Firestore.
- **Las versiones de un proyecto:** viven en `/app/projects/:id/versions` (Fase 2). Hasta
  entonces, el menú ⋮ las lista como hoy la Biblioteca.

#### E. Editor de efectos — `editor-efectos.png` · Fase 2 · L

- **Centro, "Vista previa":** Original / Con efectos, video grande, reproductor (▶, tiempo,
  barra, volumen, pantalla completa).
- **Línea de tiempo** con pestañas "Línea de tiempo / Vista de efectos", reproductor y zoom (lupas
  y deslizador). Debajo:
  - Regla de segundos y **tira de fotogramas**.
  - **Una pista por efecto** con icono, nombre y barra de color con tiradores en los extremos.
  - Cabezal cian vertical.
- **Derecha, "Efectos activos (5)":** "+ Agregar efecto" y tarjetas con icono, nombre, rango
  "00:03.2 – 00:12.8", punto de color, interruptor y ⋮.
- **"Configuración del proyecto":** Estilo, Análisis, Duración, Resolución y Versión, con
  "✎ Editar".
- **Botones:** "⤓ Descargar video" (degradado) y "⇪ Compartir".
- **Cómo encaja con el motor** (lo más importante de esta vista):
  - Los "efectos" son los momentos de la coreografía (`/api/jobs/{id}/choreography`: segundo,
    acción, persona, efecto y nota).
  - Hoy son **decenas de momentos cortos**, no 5 efectos largos. Las pistas agrupan por tipo de
    efecto o elemento: cada barra es un momento y la pista se nombra por el efecto.
  - **El interruptor** apaga un momento, **el color** cambia el color del pin y **arrastrar**
    cambia `seg` y `dur`. **"+ Agregar efecto"** añade un pin con una opción del catálogo en el
    cabezal.
  - Todo se traduce a un guion de prueba (`director/pins.py`, `pin-export`, `solo_estos: true`).
    Al aplicar se crea **una nueva versión**: no se pisa la anterior, gracias al arreglo del §2.
- **Corrección de expectativas:** no hay vista previa al instante. Aplicar cambios rehace el render
  (~11 s por segundo de video). El botón dice "Aplicar cambios (≈ N min)" y la vista lleva a la
  pantalla de proceso (C). "Con efectos" muestra la última versión renderizada.
- **Backend:**
  - `POST /api/jobs/{id}/edit` con la lista de pines: crea una versión.
  - `GET /api/jobs/{id}/frames?n=12` para la tira de fotogramas (S).
  - Campo de intensidad en los pines (no existe, M).
- **"Compartir":** Fase 3, porque necesita enlaces públicos revocables (§3.3).

### 9.6 Vistas sin diseño (plan para cuando se pidan los diseños)

| Vista | Contenido | Fase | Dependencias |
| --- | --- | --- | --- |
| Login / registro / recuperar | El diseño actual de `Login.tsx`, separado en rutas. Añadir verificación de correo al registrar (§5: hoy no se exige) | 1b | Firebase `sendEmailVerification` |
| Legales y soporte | Términos, privacidad (tratamiento de videos con caras, envío a Google y OpenAI, retención, borrado: §5) y soporte con FAQ | 1b | **Texto legal del negocio** |
| Configuración mínima | Nombre, foto, cerrar sesión. Después: seguridad (sesiones, contraseña) y **borrar cuenta con todos sus datos** | 1b mínima · 3 completa | Borrado completo (ya existe por trabajo) |
| Explorar efectos | Galería por catálogo y por efecto con videos de demostración, y "Usar este estilo" lleva al Estudio con el estilo elegido | 2 | Material de demostración propio |
| Mi plan / Consumo | Plan, créditos, minutos, análisis profundos usados (de `metrics` y `llm.call`), límites y mejora | 3 | Créditos y planes (§3.5) |
| Notificaciones (campana) | Trabajos terminados o fallidos y avisos del plan | 3 | Lista por usuario en el servidor |

### 9.7 Decisiones del usuario (tomadas)

1. **Elementos sin función todavía** (créditos, campana, "Con efectos", "Sorpréndeme",
   "Compartir", "Precios", "Agregar efecto", "Cancelar procesamiento" mientras no exista…):
   **se construyen tal cual el diseño, con datos fijos ("quemados")**, y con una anotación en el
   código de lo que falta implementar.
   - Todos los datos fijos viven en **un solo módulo**, `web/src/mocks/pendientes.ts`. Cada valor
     va comentado `// PENDIENTE(fase N): <qué falta>`. Así, `grep -rn "PENDIENTE(" web/src` da la
     lista completa de lo que falta. Los componentes nunca inventan datos sueltos.
   - Una acción sin función (p. ej. "Compartir") muestra un aviso breve "Disponible pronto". No
     navega ni simula éxito.
   - **Excepción que no cambia con esta decisión:** los **testimonios con nombre** de la landing
     ("Sofía M.", "Carlos T.", "Daniel R.", 5 estrellas) no pueden ser inventados en una página
     pública: sería publicar reseñas falsas. En desarrollo pueden usarse como datos fijos marcados
     `PENDIENTE`. **En el build de producción ese bloque no se muestra** hasta tener testimonios
     reales con permiso. Lo controla `VITE_SHOW_PENDING`: encendido en desarrollo, apagado en
     producción. Lo mismo aplica a cifras inventadas de créditos o consumo de otro usuario.
2. **Texto del botón principal: "Crear mis efectos"** (se mantiene el de la Fase 1). El resto del
   diseño, igual.
3. **Estilos por elemento: se crean.** Son catálogos Fuego, Agua, Rayo, Tierra y Viento a partir de
   Avatar con `element_mix` de un solo elemento.
   - Paso previo **S–M**: YAML en `configs/catalogs/`, más una prueba por catálogo al estilo de
     `tests/test_pins.py` (que cada uno dibuje algo) y una revisión visual con
     `tools/preview.py`.
   - Viento usa el aire de `engine/airbend.py`.
   - Las categorías de la landing se mapean a estilos reales: "Elementos" → los cinco elementales,
     "Naturaleza" → Tierra y Agua. "Fantasía", "Ciencia ficción" y "Arte visual" se muestran solo
     si se mapean a un estilo existente (p. ej. Baile neón → "Arte visual"); si no, la tarjeta va
     con datos fijos `PENDIENTE`, según la decisión 1.
   - Los chips del Estudio (Todos · Avatar · Fuego · Agua · Rayo · Tierra · Viento · Otros)
     filtran por esos catálogos; "Otros" = Baile, Pelea y Espadas.

### 9.8 Orden de implementación y verificación de las vistas

1. **Paso 0:** copiar las imágenes (§9.2) y actualizar
   `vfxglow/docs/analisis_mejoras_y_seguridad.md` con esta sección 9, para que el plan del repo
   quede igual a este.
2. **Base:** tokens e iconos, `AppShell`, barras laterales, rutas `/app/*` y redirecciones, y el
   módulo `web/src/mocks/pendientes.ts` con `VITE_SHOW_PENDING` (§9.7).
3. **Catálogos elementales** (§9.7, decisión 3): YAML, pruebas y revisión visual, antes del
   Estudio que los filtra.
4. **Vistas 1b, en este orden:** Mis proyectos (D) → Trabajo en proceso (C) → Estudio (B) → Inicio
   (A) → acceso y legales → configuración mínima. Cada vista llega con su backend S de §9.5 y en
   commits separados (backend, componentes, vista, docs). Lo que no tenga función se construye
   con datos fijos `PENDIENTE`.
5. **Fase 2:** Editor (E), Explorar, Sorpréndeme y vista previa con efectos: reemplazan sus datos fijos `PENDIENTE`.
6. **Verificación de fidelidad:** captura de cada vista a 1536 px junto al diseño, revisada
   bloque por bloque, más capturas a 1024 px y 390 px.
   - Requiere levantar `vite` y la API en local. En el último intento el clasificador del modo
     automático lo bloqueó, así que hay que pedir permiso al usuario o que lo levante él.
   - Pruebas de API para los campos nuevos (`title`, `activity`, tiempos por etapa, `/frames`,
     `/edit`) y `tsc` en verde.

**Modelo sugerido para implementarlo (§6):**
- **Opus:** la arquitectura del shell y las rutas, y el editor E.
- **Sonnet:** las vistas A–D y su backend.
- **Haiku:** la copia de imágenes, el set de iconos, los textos y las plantillas legales (estas
  con el texto que dé el negocio).

---

## 10. Vista previa mientras se edita la coreografía

### 10.1 Punto de partida

Hoy, cada cambio del editor se ve solo después de "Aplicar": un render parcial del tramo
cambiado (≈ 36 s para quitar un rayo en un video de 9 s) o completo la primera vez en una versión
preparada. La meta es que la persona vea el efecto de un cambio **al instante o en segundos**,
antes de aplicarlo, sin que la vista previa prometa algo distinto del video final.

### 10.2 Opciones evaluadas

| Opción | Veredicto | Por qué |
| --- | --- | --- |
| Reescribir el motor en el navegador (React + WebGL/JS) | ✗ | El motor (Skia + NumPy + OpenCV) tiene decenas de efectos procedurales con memoria entre fotogramas (estelas, persistencia, cierres). Serían meses y dos motores que nunca se verían igual: la vista previa contradiría el video final. React solo arma la interfaz; dibujar es trabajo de un `<canvas>`/WebGL. |
| **A. Capas precalculadas combinadas en el navegador** | ★★★ | El motor ya dibuja cada efecto como una capa RGBA antes de mezclarla. Guardar una capa por pista a baja resolución y mezclarlas en el navegador con WebGL hace instantáneos los cambios más comunes. |
| **B. Vista previa rápida en el servidor** | ★★★ | Para lo que A no puede mostrar exacto (mover, agregar), rehacer 2–3 s alrededor del cabezal a baja resolución con el mismo motor. Reutiliza el render parcial del editor. |

**Recomendación: A + B.** Instantáneo en el navegador para lo que se puede mostrar exacto, y
segundos en el servidor para lo demás. "Aplicar" sigue produciendo el video final exacto.

### 10.3 A · Capas por pista en el navegador

- **En el render** (servidor): además del MP4, escribir por cada pista del editor un video con
  transparencia a ~360 px de alto, por ejemplo WebM VP9 con alfa o, si el navegador no lo
  reproduce bien (Safari), una tira de PNG/WebP por segundo. Más una capa para "todo lo demás".
  Solo para versiones editables y con un tope de pistas (p. ej. las 12 más largas; el resto va en
  "otros").
- **En el editor** (web): un componente `LayerPreview` con WebGL que dibuja el video original y
  encima las capas en mezcla aditiva, igual que el compositor (`composite/`).
  - **Apagar / encender** una pista: la capa se oculta o se muestra. Exacto.
  - **Color**: un shader con la misma fórmula de `engine/tint.py` (conserva luminancia y núcleos
    blancos). Exacto o casi.
  - **Intensidad y tamaño**: multiplicador de la capa y escala alrededor del centro, como
    `scale_about`. Muy cercano.
  - **Mover** en el tiempo: la capa se desplaza, pero en el video real el efecto seguiría a otra
    pose del cuerpo. Se muestra con la etiqueta "Aproximado" y se ofrece B.
  - **Agregar**: no hay capa todavía. Se usa B.
- **Límites conocidos:** los efectos que interactúan entre sí (persistencia compartida, cierre en
  estrellas) pueden diferir un poco al apagarlos; el HDR del motor se aproxima en 8 bits.
- **Costo:** disco extra por versión editable (capas comprimidas a baja resolución, del orden de
  unos MB por pista y minuto: hay que medirlo) y algo más de tiempo de render la primera vez.
  Se borran con la versión.
- **Complejidad:** M–L (escribir capas en `_write`, endpoint para servirlas con la llave `?k=`,
  componente WebGL, sincronía con el reproductor).

### 10.4 B · Vista previa rápida en el servidor

- `POST /api/jobs/{id}/preview` con las ediciones pendientes y el segundo del cabezal: renderiza
  2–3 s alrededor, a media resolución, con el motor real (`render_script` con ventana) y devuelve
  un MP4 corto. Se dispara cuando la persona suelta una barra o agrega un efecto, con una espera
  breve para agrupar cambios; muestra "Generando vista previa…".
- Cola aparte y con tope diario por usuario (cada vista previa cuesta CPU, §3.5).
- Tiempo esperado: unos 5–15 s según el video. Exacto.
- **Complejidad:** S–M: casi todo existe (ventanas, warm-up, `apply_edits`).

### 10.5 Orden y modelos

1. **B primero** (S–M, Sonnet): sale casi gratis con lo que ya existe y cubre todos los cambios.
2. **A después** (M–L): Opus para el formato de capas y la mezcla en WebGL; Sonnet para el
   endpoint y la integración en el editor.
3. Verificación: comparar la vista previa contra el video aplicado (diferencia media por píxel en
   el tramo), medir el disco por pista y el tiempo de B en la máquina de producción.
