/** Avisos del navegador para cuando el revelado termina y la pestaña no está a la vista. */

const supported = (): boolean => typeof Notification !== "undefined";

/** Pide permiso. Hay que llamarlo desde un clic (el navegador lo exige); no insiste si ya se negó. */
export async function askPermission(): Promise<void> {
  if (!supported() || Notification.permission !== "default") return;
  try {
    await Notification.requestPermission();
  } catch {
    // Safari antiguo usa callbacks: sin aviso, la página sigue funcionando.
  }
}

/** Avisa solo si la pestaña está en segundo plano y la persona dio permiso. */
export function notifyDone(title: string, body: string): void {
  if (!supported() || Notification.permission !== "granted" || !document.hidden) return;
  try {
    new Notification(title, { body });
  } catch {
    // Algunos móviles solo permiten avisos desde un service worker.
  }
}
