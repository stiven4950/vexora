import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Job } from "../api/types";
import { useProfile } from "../auth/ProfileContext";
import { ROUTES } from "../routes";
import { Icon } from "./Icon";
import { ShareDialog } from "./ShareDialog";
import styles from "./CloudActions.module.css";

/** "Se borra en 3 días" / "Se borra hoy". */
export function expiresText(keepUntil: number): string {
  const days = Math.ceil((keepUntil * 1000 - Date.now()) / 86_400_000);
  return days <= 0 ? "Se borra hoy" : days === 1 ? "Se borra mañana" : `Se borra en ${days} días`;
}

interface Props {
  job: Job;
  title: string;
  onChange: (job: Job) => void;
}

/**
 * Qué se hace con el video terminado además de descargarlo, según el plan (configs/plans.yaml):
 * guardarlo en la nube (deja de vencer) y, ya guardado, compartirlo con un enlace. Sin un plan que
 * lo permita, solo se descarga antes de que venza.
 */
export function CloudActions({ job, title, onChange }: Props) {
  const { profile } = useProfile();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);
  const plan = profile?.plan;

  const run = async (call: () => Promise<Job>) => {
    setBusy(true);
    setError(null);
    try {
      onChange(await call());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const expiry = job.keep_until && !job.saved ? <small className={styles.expiry}>{expiresText(job.keep_until)}: descárgalo antes.</small> : null;

  if (!plan?.cloud_save) {
    return (
      <div className={styles.box}>
        {expiry}
        <Link to={ROUTES.plan} className={styles.locked}>
          <Icon name="lock" size={16} /> Guardar en la nube y compartir · Plan Pro
        </Link>
      </div>
    );
  }

  return (
    <div className={styles.box}>
      {job.saved ? (
        <>
          <span className={styles.saved}>
            <Icon name="cloud" size={16} /> En tu nube
          </span>
          {plan.share && (
            <button type="button" className={styles.action} onClick={() => setSharing(true)}>
              <Icon name="share" size={16} /> Compartir
            </button>
          )}
          <button
            type="button"
            className={styles.quiet}
            disabled={busy}
            onClick={() => {
              if (window.confirm(`Quitar de la nube: el enlace público dejará de funcionar y el video se borrará en ${plan.unsaved_days} días.`)) void run(() => api.unsaveJob(job.id));
            }}
          >
            Quitar de la nube
          </button>
        </>
      ) : (
        <>
          {expiry}
          <button type="button" className={styles.action} disabled={busy} onClick={() => void run(() => api.saveJob(job.id))}>
            <Icon name="cloud" size={16} /> {busy ? "Guardando…" : "Guardar en mi nube"}
          </button>
          {plan.share && <small className={styles.hint}>Guárdalo para poder compartirlo con un enlace.</small>}
        </>
      )}
      {error && (
        <small role="alert" className={styles.error}>
          {error}
        </small>
      )}
      {sharing && <ShareDialog jobId={job.id} title={title} onClose={() => setSharing(false)} />}
    </div>
  );
}
