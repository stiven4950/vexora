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
| `/` Estudio | 01 subir el plano (arrastrar o elegir), 02 elegir coreografía o preset (cada tarjeta anima sus colores) y "Revelar en neón". No hay semilla: el servidor prueba varias coreografías y usa la mejor |
| `/jobs/:id` | Mientras procesa: anillo de progreso, etapas (lectura del movimiento → coreografía → revelado) y consola en vivo. Al terminar: comparador antes/después con cortina arrastrable, línea de tiempo con cada reacción de la coreografía (clic para saltar), descarga MP4 y "Probar otra versión" (la siguiente mejor coreografía, u otro estilo, sobre el mismo video; el análisis queda en caché) |
| `/library` | Todos los revelados con miniatura, estado y progreso |

Atajos en el comparador: espacio (reproducir/pausar), flechas (fotograma a fotograma).

## API

| Método | Ruta | Uso |
| --- | --- | --- |
| GET | `/api/styles` | Catálogos y presets (título, descripción, paleta, acciones) |
| POST | `/api/jobs` | multipart: `video`, `style`, `style_kind` (catalog/preset), `seed` |
| GET | `/api/jobs`, `/api/jobs/{id}` | Estado y progreso |
| GET | `/api/jobs/{id}/events` | Server-Sent Events con el estado en vivo |
| POST | `/api/jobs/{id}/variations` | JSON `{style_kind, style, seed}`: otra versión del mismo video |
| GET | `/api/jobs/{id}/output` · `/original` · `/thumbnail` · `/choreography` | Videos (con rangos para adelantar), miniatura y decisiones |
| DELETE | `/api/jobs/{id}` | Borra el trabajo |

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
