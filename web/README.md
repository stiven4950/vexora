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

| Ruta | Qué hace |
| --- | --- |
| `/` Estudio | 01 subir el plano (arrastrar o elegir; avisa de duración y tamaño antes de subir), 02 elegir coreografía o preset (cada tarjeta anima sus colores). Temporada, fuego y rayo, vestuario y tipo de análisis están en "Opciones avanzadas", plegadas, con lo elegido a la vista. La barra inferior resume archivo, estilo y tiempo estimado, y "Crear mis efectos" pide permiso de avisos. No hay semilla: el servidor prueba varias coreografías y usa la mejor. El análisis profundo (experimental) solo se activa en las cuentas que lo tienen |
| `/jobs/:id` | Mientras procesa: anillo de progreso, etapas (lectura del movimiento → coreografía → revelado), posición en la cola y tiempo estimado, el avance en el título de la pestaña y un aviso del navegador al terminar; el registro técnico queda tras "Ver detalles técnicos". Si falla: mensaje claro y "Reintentar". Al terminar: comparador antes/después con cortina arrastrable, línea de tiempo con cada reacción de la coreografía (clic para saltar), descarga MP4 y "Probar otra versión" (la siguiente mejor coreografía, u otro estilo, sobre el mismo video; el análisis queda en caché) |
| `/library` | Un video por tarjeta, con sus versiones debajo (portada, estado y progreso) |

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
| DELETE | `/api/jobs/{id}` | Borra el trabajo, su MP4 y, si nadie más los usa, el video y su análisis (409 si se está procesando) |

Los trabajos se procesan de uno en uno. Estado y videos subidos en `api_data/` (no se versiona).
Si el servidor se reinicia a mitad de un trabajo, queda marcado como interrumpido.

## Estructura

```text
web/src/
  api/          tipos, cliente y formato (alineados con src/vfxglow/api/server.py)
  hooks/        useJob: estado en vivo por SSE con respaldo de sondeo
  components/   Shell, Dropzone, StyleCard, NeonPreview (lienzo animado), Darkroom, CompareViewer, Button, Icon
  pages/        Studio, JobPage, Library
  styles/       tokens de diseño, grano de película y auroras
```
