/**
 * Datos fijos ("quemados") de lo que los diseños muestran y todavía no tiene función real.
 *
 * Cada valor lleva `PENDIENTE(fase N): <qué falta>`. `grep -rn "PENDIENTE(" web/src` lista todo lo
 * que falta por implementar. Los componentes no inventan datos sueltos: los leen de aquí.
 *
 * Con SHOW_PENDING apagado (producción) lo que sería engañoso para el público (testimonios con
 * nombre, cifras ajenas) no se muestra. Se enciende en desarrollo o con VITE_SHOW_PENDING=1.
 */

export const SHOW_PENDING: boolean = import.meta.env.DEV || import.meta.env.VITE_SHOW_PENDING === "1";

/** Avisa que una acción del diseño aún no hace nada; no navega ni simula un éxito. */
export function soonNotice(what: string): void {
  window.alert(`${what} estará disponible pronto.`);
}

// PENDIENTE(fase 3): notificaciones reales por usuario (trabajos terminados o fallidos, avisos del
// plan). Hoy son datos fijos.
export const NOTIFICATIONS = [
  { id: "n1", title: "Tu video está listo", text: "Poderes de Avatar terminó de procesarse.", when: "hace 5 min" },
  { id: "n2", title: "Bienvenido a VEXORA", text: "Sube tu primer video y crea tus efectos.", when: "ayer" },
] as const;

// PENDIENTE(fase 3): créditos y plan reales (docs/analisis_mejoras_y_seguridad.md, §3.5).
export const PLAN = { name: "Free", creditsLeft: 3, creditsTotal: 5, creditsPerRender: 1 } as const;

// Respaldo de "Sorpréndeme con IA" cuando no hay análisis del video (aún sin subir, o falló): elige entre
// estos estilos. Con análisis, el Estudio usa la recomendación real del servidor.
export const SURPRISE_STYLES = ["avatar", "baile", "pelea"] as const;

// PENDIENTE(fase 2): respaldo de la vista previa "Con efectos" cuando aún no hay subida analizada: un
// fotograma de demostración del estilo. Con subida lista, el Estudio genera ~3 s reales (§3.1).
export const PREVIEW_WITH_EFFECTS_NOTE = "Disponible tras el análisis del video.";

// PENDIENTE(fase 3): testimonios reales con permiso. Con nombre e inventados no se publican:
// solo se ven con SHOW_PENDING.
export const TESTIMONIALS = [
  { quote: "Me encantó lo fácil que es de usar. En minutos tenía un video con efectos increíbles.", who: "Sofía M." },
  { quote: "La calidad de los efectos es brutal. Ideal para creadores como yo.", who: "Carlos T." },
] as const;
export const FEATURED_QUOTE = { quote: "VEXORA convierte lo cotidiano en algo increíble. Es como tener un estudio de efectos visuales en el bolsillo.", who: "Daniel R.", stars: 5 } as const;
