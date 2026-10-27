import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { PreviewView, StudioPreviewOpts } from "../api/types";

/** Las señales que hacen que un estilo analice el video a su manera (pipeline.apply_catalog_needs). */
export const OWN_ANALYSIS_NEEDS = ["blades", "props"];

/** Lo que tarda en dibujarse la vista previa de ~3 s a 480 px (medido en un Mac M1: 3-12 s según el estilo). */
export const PREVIEW_ESTIMATE_S = 15;
const POLL_MS = 1500;
const BLOCKED = "analiza el video a su manera";

interface State {
  key: string;
  view: PreviewView | null;
  error: string | null;
  busy: boolean;
}

/**
 * La vista previa "Con efectos" del Estudio: se pide con un botón, se consulta hasta que termina y
 * queda desactualizada si cambian el estilo o las opciones. `blocked`: el estilo analiza el video a su
 * manera y no se puede ver antes de crear los efectos: se sabe por sus `needs` o, si no, por el 409.
 */
export function useStudioPreview(uploadId: string | null, opts: StudioPreviewOpts | null, ownAnalysis = false) {
  const key = uploadId && opts ? JSON.stringify([uploadId, opts]) : "";
  const [state, setState] = useState<State | null>(null);
  const [blockedStyles, setBlockedStyles] = useState<string[]>([]);
  const token = useRef(0);
  useEffect(() => () => void (token.current += 1), []);
  // Otra subida (otro video): lo anterior ya no vale ni se sigue consultando.
  useEffect(() => {
    token.current += 1;
    setState(null);
  }, [uploadId]);

  const start = useCallback(async () => {
    if (!uploadId || !opts) return;
    const mine = ++token.current;
    const sent = key;
    const alive = () => token.current === mine;
    setState({ key: sent, view: null, error: null, busy: true });
    try {
      let view = await api.uploadPreview(uploadId, opts);
      while (view.status === "rendering") {
        if (!alive()) return;
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        if (!alive()) return;
        view = await api.getUploadPreview(uploadId, view.preview_id);
      }
      if (alive()) setState({ key: sent, view: view.status === "ready" ? view : null, error: view.status === "ready" ? null : (view.error ?? "No pudimos generar la vista previa."), busy: false });
    } catch (cause) {
      if (!alive()) return;
      const text = cause instanceof Error ? cause.message : String(cause);
      if (cause instanceof ApiError && cause.status === 409 && text.includes(BLOCKED)) setBlockedStyles((cur) => [...cur, opts.style]);
      setState({ key: sent, view: null, error: text, busy: false });
    }
  }, [uploadId, opts, key]);

  const mine = state && state.key === key ? state : null;
  return {
    /** Lista y vigente. */
    ready: mine?.view?.status === "ready" ? mine.view : null,
    /** Hay una lista, pero de otro estilo u otras opciones. */
    outdated: !!state?.view && state.key !== key,
    generating: !!state?.busy && state.key === key,
    error: mine?.error ?? null,
    blocked: !!opts && (ownAnalysis || blockedStyles.includes(opts.style)),
    start,
  };
}
