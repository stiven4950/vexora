import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { ShareLink } from "../api/types";
import { Button } from "./Button";
import { Icon } from "./Icon";
import styles from "./ShareDialog.module.css";

/** Compartir un video terminado con un enlace público que se puede revocar (api/shares.py). */
export function ShareDialog({ jobId, title, onClose }: { jobId: string; title: string; onClose: () => void }) {
  const [link, setLink] = useState<ShareLink | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  const close = useCallback(onClose, [onClose]);
  useEffect(() => {
    ref.current?.focus();
    const handler = (event: KeyboardEvent) => event.key === "Escape" && close();
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [close]);

  useEffect(() => {
    let alive = true;
    api
      .getShare(jobId)
      .then((found) => alive && setLink(found))
      .catch((cause: unknown) => {
        if (!alive) return;
        if (cause instanceof ApiError && cause.status === 404) setLink(null);
        else setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      alive = false;
    };
  }, [jobId]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const url = link ? `${window.location.origin}${link.path}` : "";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      input.current?.select(); // sin permiso del portapapeles: queda seleccionado para copiar a mano
      return;
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={styles.overlay} onMouseDown={onClose}>
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="share-title" tabIndex={-1} ref={ref} onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <h2 id="share-title">Compartir video</h2>
          <button type="button" className={styles.close} onClick={onClose} aria-label="Cerrar">
            <Icon name="close" size={18} />
          </button>
        </header>
        <p className={styles.lead}>
          Cualquiera con el enlace puede ver <strong>{title}</strong> sin iniciar sesión. Puedes dejar de compartirlo cuando quieras.
        </p>
        {link === undefined && !error && <p className={styles.muted}>Cargando…</p>}
        {link === null && (
          <Button icon="share" disabled={busy} onClick={() => run(async () => setLink(await api.createShare(jobId)))}>
            {busy ? "Creando el enlace…" : "Crear enlace público"}
          </Button>
        )}
        {link && (
          <>
            <div className={styles.field}>
              <input ref={input} readOnly value={url} aria-label="Enlace público" onFocus={(event) => event.currentTarget.select()} />
              <button type="button" onClick={() => void copy()}>
                <Icon name={copied ? "check" : "external"} size={16} /> {copied ? "Copiado" : "Copiar"}
              </button>
            </div>
            <p className={styles.muted}>
              {link.views === 1 ? "1 visita" : `${link.views} visitas`} · El video se mostrará con el nombre del proyecto y sin datos de tu cuenta.
            </p>
            <Button
              variant="danger"
              icon="cancel"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await api.revokeShare(jobId);
                  setLink(null);
                })
              }
            >
              Dejar de compartir
            </Button>
          </>
        )}
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
