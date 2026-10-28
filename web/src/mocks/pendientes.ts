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

// PENDIENTE(fase 3): libro de créditos real (docs/analisis_mejoras_y_seguridad.md, §3.5): saldo con
// reservas por trabajo y cobros idempotentes, y las reglas de consumo por efecto y render (hoy sin
// definir). Mientras tanto el saldo, la renovación y el costo por render son datos fijos del diseño.
export const CREDITS = {
  balance: 42,
  /** Créditos que se renuevan y cuándo (ISO). */
  renewal: { credits: 5, date: "2026-11-01" },
  creditsPerRender: 1,
  // PENDIENTE(fase 3): consumo por proyecto de los últimos 30 días, calculado desde el libro de créditos.
  usage: { total: 150, effects: 85, renders: 12, other: 5 },
  // PENDIENTE(fase 3): historial de compras y recibos reales del proveedor de pagos.
  purchases: [
    { id: "p1", title: "Paquete de 100 créditos", when: "18 oct 2026 · 10:24 a. m.", amount: 8.99, icon: "card" },
    { id: "p2", title: "Paquete de 50 créditos", when: "3 oct 2026 · 6:17 p. m.", amount: 4.99, icon: "card" },
    { id: "p3", title: "Bono de bienvenida +10 créditos", when: "1 sep 2026 · 12:00 p. m.", amount: 0, icon: "gift" },
  ],
  // PENDIENTE(fase 3): movimientos reales (compras, renovaciones, consumo por proyecto, bonos y reembolsos).
  movements: [
    { id: "m1", date: "26 oct 2026", kind: "consumo", project: "Poderes de Avatar", credits: -1, status: "Completado", value: null },
    { id: "m2", date: "24 oct 2026", kind: "consumo", project: "Baile en la azotea", credits: -2, status: "Completado", value: null },
    { id: "m3", date: "21 oct 2026", kind: "reembolso", project: "Pelea en el callejón", credits: 1, status: "Reembolsado", value: null },
    { id: "m4", date: "18 oct 2026", kind: "compra", project: null, credits: 100, status: "Pagado", value: 8.99 },
    { id: "m5", date: "12 oct 2026", kind: "consumo", project: "Pelea en el callejón", credits: -1, status: "Reembolsado", value: null },
    { id: "m6", date: "3 oct 2026", kind: "compra", project: null, credits: 50, status: "Pagado", value: 4.99 },
    { id: "m7", date: "1 oct 2026", kind: "renovación", project: null, credits: 5, status: "Aplicado", value: null },
    { id: "m8", date: "1 sep 2026", kind: "bono", project: null, credits: 10, status: "Aplicado", value: 0 },
  ],
} as const;

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
