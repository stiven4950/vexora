# Plan: cuentas de usuario, biblioteca, nube, compartir y planes

Estado: fase 1 (ingreso con Google y API protegida) implementada; el resto, propuesta. El modelo de negocio no está definido; el plan deja los
permisos por plan en un solo lugar para cambiarlos sin tocar el resto.

## Punto de partida

- La API (`api/server.py`, FastAPI) y la cola de trabajos (`api/jobs.py`) son de **un solo
  usuario**: estado en `api_data/jobs.json`, videos en `api_data/uploads/<id>/`, sin
  autenticación.
- El análisis de cada video se guarda en `runs/<video>-<hash>/` y se reutiliza por el hash del
  video: reprocesar con otro estilo no repite el análisis. Esa caché es la base de la biblioteca
  de análisis por usuario.
- La web (React, `web/src`) tiene Estudio, Biblioteca y la página del trabajo, y descarga el MP4
  (`/api/jobs/{id}/output?download=1`).

## 1. Autenticación con Google (Firebase Auth)

- **Web:** Firebase Auth con el proveedor de Google (`signInWithPopup` en escritorio y
  `signInWithRedirect` en móvil). La sesión la mantiene el SDK.
- **API:** cada petición lleva `Authorization: Bearer <ID token>`. Una dependencia de FastAPI lo
  verifica con `firebase-admin` (`auth.verify_id_token`) y entrega el `uid`. Sin token válido,
  responde 401.
- **Usuario:** el primer ingreso crea su documento en `users/{uid}` (nombre, correo, plan, fecha de
  alta).
- **Desarrollo:** el emulador de Firebase Auth, o la variable `VEXORA_AUTH=off` para trabajar en
  local con un usuario fijo. Esta variable no se puede activar en producción.
- **Eventos en vivo:** el progreso por SSE (`/api/jobs/{id}/events`) no admite cabeceras desde
  `EventSource`. Se usa un token corto de un solo uso en la URL, emitido por la API.

## 2. Datos por usuario

Firestore, en el mismo proyecto de Firebase, reemplaza a `jobs.json`:

| Colección | Contenido |
| --- | --- |
| `users/{uid}` | Perfil, plan, consumo del mes (análisis profundos, almacenamiento) |
| `videos/{id}` | Dueño, nombre, hash, duración, dónde está el original (local o nube) |
| `analyses/{id}` | Dueño, hash del video, nivel (básico, estándar, profundo), fecha, ubicación de los archivos del análisis, costo de IA |
| `jobs/{id}` | Dueño, video, análisis, estilo, semilla o versión, temporada, estado, salida |

- Cada consulta filtra por dueño. Un usuario no ve ni puede pedir el trabajo de otro: la API
  devuelve 404, no 403, para no revelar que existe.
- Los archivos de trabajo pasan de `runs/<video>-<hash>` a `runs/<uid>/<video>-<hash>`.

## 3. Biblioteca de análisis: reprocesar sin pagar de nuevo

- Cada análisis queda guardado con su nivel: pistas, eventos, brief y, en el nivel profundo,
  `scene_reading.json` (`docs/plan_director_ia.md`).
- Desde la biblioteca, el usuario abre un video y crea versiones: otro estilo, otra temporada,
  "otra versión" del coreógrafo, o un guion de prueba editado. Ninguna repite el análisis ni la
  lectura de la IA.
- **Subir de nivel:** pasar un análisis de estándar a profundo solo agrega la lectura profunda
  sobre el análisis ya hecho, y es lo único que se cobra.
- **Retención:** el análisis pesa poco (las pistas y eventos son JSON, unos MB por video) y se
  conserva aunque se borre el video. Si después vuelve a subir el mismo video, se reconoce por el
  hash. Cuánto tiempo se guarda en el plan gratuito es una decisión del modelo de negocio.

## 4. Guardado: MP4 siempre, nube opcional

- **MP4:** la descarga queda siempre disponible para todos los planes, como hoy.
- **Nube (opcional, con costo):** guarda el original, las versiones renderizadas y el análisis
  para verlos desde cualquier dispositivo.

### ¿Cloudinary o Firebase Storage?

| | Firebase Storage (Google Cloud Storage) | Cloudinary |
| --- | --- | --- |
| Encaje | Mismo proyecto que Auth y Firestore; reglas de acceso por `uid` | Servicio aparte, con sus propias claves |
| Costo | Por GB guardado y descargado, predecible | Por "créditos" que suman almacenamiento, ancho de banda y transformaciones; el video los consume rápido |
| Fortaleza | Guardar y servir archivos con URLs firmadas que caducan | Transcodificar, recortar, marcas de agua y miniaturas al vuelo, entrega optimizada para redes |
| Marca de agua | La ponemos nosotros al componer (ffmpeg) | Se puede poner al servir |

**Recomendación: Firebase Storage.** Encaja con la autenticación, las reglas por usuario son
nativas y el costo del video es más predecible. La marca de agua y los formatos para redes los
hace el motor al componer, así que no hace falta Cloudinary para eso. Si más adelante se necesita
entrega optimizada para muchas reproducciones, Cloudinary puede sumarse solo como distribución.

Ruta de los archivos: `users/{uid}/videos/{video}/original.mp4`, `.../renders/{job}.mp4` y
`.../analysis/`. Las reglas solo dejan leer y escribir al dueño; la descarga y el compartir usan
URLs firmadas con caducidad.

## 5. Compartir en redes

En orden de esfuerzo:

1. **Compartir nativo:** en el móvil, `navigator.share` con el archivo MP4 abre el menú del
   sistema (Instagram, TikTok, WhatsApp...). Funciona sin integrar cada red.
2. **Enlace para compartir:** solo con la nube. Una página pública del video (`/v/{id}`), con
   vista previa para redes (Open Graph), y que el dueño puede desactivar.
3. **Publicar directo** en TikTok, Instagram o YouTube: cada red exige registrar la app y pasar
   una revisión. Queda para cuando haya usuarios que lo pidan.

Formatos: el MP4 se compone en 9:16 vertical cuando el original lo es, con un tamaño y bitrate
que las redes aceptan sin recomprimir de más.

## 6. Planes y permisos

Los permisos se deciden en el servidor, en un solo módulo (`api/plans.py`), a partir del plan del
usuario:

```python
PLANS = {
    "free":  {"watermark": True,  "deep_analysis": False, "cloud": False, "max_seconds": 60},
    "pro":   {"watermark": False, "deep_analysis": True,  "cloud": True,  "max_seconds": 300},
}
```

Los valores son de ejemplo: los define el modelo de negocio. El análisis profundo y la nube
también pueden venderse sueltos (por uso), además de dentro de un plan.

### Marca de agua (plan gratuito)

- La pone el motor al componer, con ffmpeg (`overlay` y `drawtext`): el logo de VEXORA en una
  esquina, discreto, y el hashtag de la app (por ejemplo `#VexoraFX`), más una placa final de
  1 segundo con el logo.
- **En el plan gratuito no se guarda una copia sin marca.** Si existiera, la marca se podría
  saltar; al pasar a pago se vuelve a componer sin marca a partir del análisis guardado, sin
  repetirlo.
- En el plan de pago no hay marca.

### Cobro

Queda para cuando se defina el modelo. El diseño solo pide:

- un `plan` y un consumo por usuario en Firestore;
- un webhook del proveedor de pago que actualice el plan. Stripe es lo habitual; para
  Latinoamérica conviene evaluar Mercado Pago.

## 7. Procesamiento con varios usuarios

Hoy los trabajos corren de uno en uno en la misma máquina (Mac con MPS). Con usuarios reales hace
falta decidir dónde corre el análisis (servidor con GPU, cola de trabajos, límite por usuario).
No bloquea las fases 1-3, pero sí la salida a producción. Queda como decisión abierta.

## 8. Privacidad

Los videos son de personas:

- **Términos y consentimiento:** el usuario declara que tiene permiso de las personas que aparecen.
- **Borrar todo:** un botón que elimina videos, renders y análisis del usuario, en el disco y en la
  nube.
- **Uso de los videos:** no se usan para entrenar sin un consentimiento aparte y explícito.
- **Accesos:** los registros de acceso a archivos en la nube quedan activos.

## Orden y entregables

| Fase | Entregable | Criterio de terminado |
| --- | --- | --- |
| 1 | Ingreso con Google y API protegida | Sin sesión no hay acceso; cada usuario ve solo lo suyo (pruebas con dos usuarios) |
| 2 | Firestore en lugar de `jobs.json`; archivos por usuario | Lo de hoy funciona igual, por usuario |
| 3 | Biblioteca de análisis y versiones sin reanalizar | Una nueva versión de un video ya analizado no pasa por la etapa de análisis |
| 4 | `api/plans.py` y marca de agua en el plan gratuito | El MP4 gratuito sale con marca y no hay copia limpia; el de pago, sin marca |
| 5 | Nube opcional con Firebase Storage | Subir, ver y borrar desde otro dispositivo; URLs que caducan |
| 6 | Compartir nativo y enlace público | Se comparte desde el móvil; el enlace se puede desactivar |
| 7 | Cobro | Cuando exista el modelo de negocio |

## Riesgos y límites

- **Costo de la nube:** el video pesa; hay que poner límites de almacenamiento por plan y borrar
  los renders intermedios.
- **Marca de agua:** se puede recortar o tapar con otra app. Disuade, no impide.
- **Publicar directo en redes:** depende de revisiones de cada plataforma, fuera de nuestro control.
- **Procesamiento:** mientras corra en una sola máquina, varios usuarios a la vez esperan en la
  cola.
