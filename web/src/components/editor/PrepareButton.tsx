import { useState } from "react";

import { api } from "../../api/client";
import type { Job } from "../../api/types";
import { Icon } from "../Icon";

interface Props {
  job: Job;
  className?: string;
  /** La versión ya preparada (editable). */
  onDone: (job: Job) => void;
}

/** "Preparar para editar": deja editable una versión terminada antes del editor (unos segundos). */
export function PrepareButton({ job, className, onDone }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const prepare = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await api.prepareEdit(job.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };
  return (
    <>
      <button type="button" className={className} onClick={prepare} disabled={busy}>
        <Icon name="wand" size={18} /> {busy ? "Preparando…" : "Preparar para editar"}
      </button>
      {error && (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #ff6b6b)", fontSize: 13 }}>
          {error}
        </p>
      )}
    </>
  );
}
