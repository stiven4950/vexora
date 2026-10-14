import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Job } from "../api/types";

/** Estado en vivo de un trabajo: eventos SSE mientras corre; sondeo si el navegador corta el stream. */
export function useJob(id: string | undefined): { job: Job | null; error: string | null } {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let closed = false;
    let source: EventSource | null = null;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const next = await api.job(id);
        if (closed) return;
        setJob(next);
        if (next.status === "queued" || next.status === "running") timer = window.setTimeout(poll, 1500);
      } catch (cause) {
        if (!closed) setError(cause instanceof Error ? cause.message : String(cause));
      }
    };

    api
      .job(id)
      .then((first) => {
        if (closed) return;
        setJob(first);
        if (first.status === "done" || first.status === "failed") return;
        if (!first.events_url) return;
        source = new EventSource(first.events_url);
        source.onmessage = (event) => setJob(JSON.parse(event.data) as Job);
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
