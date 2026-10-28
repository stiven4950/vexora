import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Job } from "../api/types";
import { JOB_FINISHED_EVENT } from "./useNotifications";

/** Estado en vivo de un trabajo: eventos SSE mientras corre; sondeo si el navegador corta el stream. */
export function useJob(id: string | undefined): { job: Job | null; error: string | null } {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let closed = false;
    let source: EventSource | null = null;
    let timer: number | undefined;
    let lastStatus: Job["status"] | null = null;
    // Si el trabajo pasa de en curso a terminado o fallido ante los ojos de la persona, la campana se refresca.
    const show = (next: Job) => {
      if ((next.status === "done" || next.status === "failed") && (lastStatus === "queued" || lastStatus === "running")) window.dispatchEvent(new Event(JOB_FINISHED_EVENT));
      lastStatus = next.status;
      setJob(next);
    };

    const poll = async () => {
      try {
        const next = await api.job(id);
        if (closed) return;
        show(next);
        if (next.status === "queued" || next.status === "running") timer = window.setTimeout(poll, 1500);
      } catch (cause) {
        if (!closed) setError(cause instanceof Error ? cause.message : String(cause));
      }
    };

    api
      .job(id)
      .then((first) => {
        if (closed) return;
        show(first);
        if (first.status === "done" || first.status === "failed") return;
        if (!first.events_url) return;
        source = new EventSource(first.events_url);
        source.onmessage = (event) => show(JSON.parse(event.data) as Job);
        source.onerror = () => {
          source?.close();
          void poll();
        };
      })
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)));

    return () => {
      closed = true;
      source?.close();
      window.clearTimeout(timer);
    };
  }, [id]);

  return { job, error };
}
