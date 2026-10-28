import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { AppNotification } from "../api/types";

/** Los trabajos que la persona está viendo avisan con este evento cuando terminan o fallan. */
export const JOB_FINISHED_EVENT = "vexora:job-finished";
const POLL_MS = 30_000;
// El servidor crea el aviso un instante después de marcar el trabajo como terminado.
const AFTER_FINISH_MS = 1200;

/** Los avisos reales de la campana: se consultan cada ~30 s y al terminar un trabajo que se está viendo. */
export function useNotifications(): { items: AppNotification[]; unread: number; markAllRead: () => void } {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);

  const load = useCallback(async () => {
    try {
      const view = await api.notifications();
      setItems(view.items);
      setUnread(view.unread);
    } catch {
      // sin API o sin sesión: la campana queda como estaba
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, POLL_MS);
    let later: number | undefined;
    const onFinished = () => {
      window.clearTimeout(later);
      later = window.setTimeout(() => void load(), AFTER_FINISH_MS);
    };
    window.addEventListener(JOB_FINISHED_EVENT, onFinished);
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(later);
      window.removeEventListener(JOB_FINISHED_EVENT, onFinished);
    };
  }, [load]);

  const markAllRead = useCallback(() => {
    setUnread(0);
    api
      .markRead("all")
      .then((view) => setUnread(view.unread))
      .catch(() => void load());
  }, [load]);

  return { items, unread, markAllRead };
}
