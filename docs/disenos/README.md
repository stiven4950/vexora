# Diseños de referencia de las vistas

El resultado debe quedar **fiel** a estos diseños: misma estructura, jerarquía, espaciado, colores,
tipografía e iconografía. Están descritos bloque por bloque en
[`docs/analisis_mejoras_y_seguridad.md`](../analisis_mejoras_y_seguridad.md), §9.

| Imagen | Vista | Ruta | Fase |
| --- | --- | --- | --- |
| `landing.png` | Inicio público | `/` | 1b |
| `estudio.png` | Estudio | `/app/studio` | 1b |
| `procesando.png` | Trabajo en proceso (el resultado y el error usan el mismo marco) | `/app/jobs/:id` | 1b |
| `mis-proyectos.png` | Mis proyectos | `/app/library` | 1b |
| `editor-efectos.png` | Editor de efectos | `/app/projects/:id/edit` | 2 |

Lo que el diseño muestra y aún no tiene función (créditos, campana, "Con efectos", "Sorpréndeme",
"Compartir", "Precios"…) se construye con datos fijos en `web/src/mocks/pendientes.ts`, cada uno
marcado `PENDIENTE(fase N)`. `grep -rn "PENDIENTE(" web/src` lista lo que falta.

Los testimonios con nombre de la landing no se publican si no son reales: solo se ven con
`VITE_SHOW_PENDING=1` (desarrollo).
