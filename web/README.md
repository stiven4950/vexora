# VFX Glow · Estudio web

Interfaz React + TypeScript (Vite) para todo el flujo de edición: subir un plano, elegir estilo y
versión, seguir el revelado en vivo y comparar antes/después. Habla con la API de Python
(`vfxglow-api`, FastAPI), que corre el pipeline.

## Arrancar (desarrollo)

Dos terminales, desde la carpeta `vfxglow/`:

```bash
# 1. API (puerto 8000; documentación interactiva en http://127.0.0.1:8000/docs)
source .venv/bin/activate
pip install -e ".[api]"        # la primera vez
vfxglow-api

# 2. Front (puerto 5173, con recarga en caliente; /api se reenvía a la API)
cd web
npm install                    # la primera vez
npm run dev
```

Abrir http://localhost:5173.

## Arrancar (un solo proceso)

```bash
cd web && npm run build && cd ..
vfxglow-api                    # sirve también el front compilado en http://127.0.0.1:8000
```

## Pantallas

Los diseños de referencia están en [`docs/disenos/`](../docs/disenos/README.md); el resultado debe quedar fiel a ellos.
Las rutas viven en `src/routes.ts`. Lo que un diseño muestra y aún no tiene función (créditos, campana, "Con
efectos", "Sorpréndeme", "Compartir"…) lee datos fijos de `src/mocks/pendientes.ts`, cada uno marcado
`PENDIENTE(fase N)`: `grep -rn "PENDIENTE(" web/src` lista lo que falta. Los testimonios con nombre solo se ven
con `VITE_SHOW_PENDING=1` (o en desarrollo).

| Ruta | Qué hace |
| --- | --- |
| `/` Inicio | Página pública: comparador antes/después, beneficios, estilos destacados (de `/api/styles`) y cierre. Con sesión va al estudio, salvo con `?inicio=1` |
| `/login` · `/register` · `/forgot-password` | Acceso con correo, Google o GitHub; al registrarse se envía el correo de verificación |
| `/terms` · `/privacy` · `/support` | Documentos legales y ayuda (el texto lo redacta el negocio) |
| `/app/studio` Estudio | 1 El plano (soltar o elegir, con su ficha y avisos de duración y tamaño), 2 El estilo (filtros por elemento y "Sorpréndeme"), 3 Temporada, 4 Fuego y rayo (solo en los estilos que lo dibujan), 5 Vestuario, 6 Análisis (el profundo, deshabilitado sin acceso). Columna fija con vista previa, datos del video, resumen y "Crear mis efectos" con el tiempo estimado |
| `/app/jobs/:id` | En cola o proceso: las 4 etapas con su tiempo, el anillo general, el detalle por etapa, la actividad reciente, la ficha y la configuración aplicada, y "Cancelar procesamiento". Aviso del navegador al terminar y avance en el título de la pestaña. Si falla: mensaje claro y "Reintentar". Al terminar: comparador antes/después, línea de tiempo con cada reacción, descarga MP4 y "Probar otra versión" |
| `/app/library` Mis proyectos | Un video por tarjeta con estado, etiquetas, fecha y resolución; búsqueda, filtros por estado con contador, descarga, reintento, renombrar y borrar por versión; paginación |
| `/app/settings` | Perfil, estado del correo (con reenvío de la verificación) y cerrar sesión |
| `/app/explore` · `/app/plan` · `/app/projects/:id` | En desarrollo (fases 2 y 3) |

Las rutas viejas `/jobs/:id` y `/library` redirigen a las nuevas.

Atajos en el comparador: espacio (reproducir/pausar), flechas (fotograma a fotograma).

## API

| Método | Ruta | Uso |
| --- | --- | --- |
| GET | `/api/styles` | Catálogos y presets (título, descripción, paleta, acciones) |
| GET | `/api/limits` | Duración, tamaño y lado máximos del video, y si la cuenta tiene análisis profundo |
| POST | `/api/jobs` | multipart: `video`, `style`, `style_kind` (catalog/preset), `seed` |
| GET | `/api/jobs`, `/api/jobs/{id}` | Estado y progreso, con `estimate_s` (segundos esperados) y `queue_ahead` (trabajos antes en la cola) |
| GET | `/api/jobs/{id}/events` | Server-Sent Events con el estado en vivo |
| POST | `/api/jobs/{id}/variations` | JSON `{style_kind, style, seed}`: otra versión del mismo video |
| GET | `/api/jobs/{id}/output` · `/original` · `/thumbnail` · `/choreography` | Videos (con rangos para adelantar), miniatura y decisiones |
| POST | `/api/jobs/{id}/retry` | Vuelve a procesar un trabajo que falló (409 si no falló) |
| POST | `/api/jobs/{id}/cancel` | Cancela un trabajo en cola (se borra ya) o en curso (se corta en unos segundos y se borra); 409 si ya terminó |
| PATCH | `/api/jobs/{id}` | JSON `{title}`: renombra el proyecto (el video y todas sus versiones); vacío = el nombre del archivo |
| DELETE | `/api/jobs/{id}` | Borra el trabajo, su MP4 y, si nadie más los usa, el video y su análisis (409 si se está procesando) |

Los trabajos se procesan de uno en uno. Estado y videos subidos en `api_data/` (no se versiona).
Si el servidor se reinicia a mitad de un trabajo, queda marcado como interrumpido.

## Estructura

```text
web/src/
  api/          tipos, cliente y formato (alineados con src/vfxglow/api/server.py)
  hooks/        useJob: estado en vivo por SSE con respaldo de sondeo
  components/   Shell (barra superior + barras laterales), Dropzone, StyleTile, ProcessingView, ProjectCard,
                CompareViewer, ChoreographyPanel, NeonPreview (lienzo animado), Icon…
  mocks/        datos fijos de lo que aún no tiene función (pendientes.ts)
  pages/        Landing, Login, Studio, JobPage, Library, Settings, Placeholder
  styles/       tokens de diseño, grano de película y auroras
```
