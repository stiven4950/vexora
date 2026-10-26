import { useEffect, useState } from "react";

import { approx, mmss } from "../api/format";
import type { Style } from "../api/types";
import { rgb } from "../api/format";
import { PLAN, PREVIEW_WITH_EFFECTS_NOTE } from "../mocks/pendientes";
import { Button } from "./Button";
import { Icon } from "./Icon";
import { NeonPreview } from "./NeonPreview";
import { Segmented } from "./Segmented";
import type { VideoMeta } from "./Dropzone";
import styles from "./StudioAside.module.css";

interface Props {
  file: File | null;
  meta: VideoMeta | null;
  style: Style | null;
  season: string | null;
  wardrobe: string;
  analysis: string;
  looks: string | null;
  upload: number | null;
  error: string | null;
  canLaunch: boolean;
  onLaunch: () => void;
}

type View = "original" | "effects";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.row}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

/** La columna fija del Estudio: vista previa, datos del video, resumen del proyecto y el botón de crear. */
export function StudioAside({ file, meta, style, season, wardrobe, analysis, looks, upload, error, canLaunch, onLaunch }: Props) {
  const [view, setView] = useState<View>("original");
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) {
      setUrl(null);
      return;
    }
    const created = URL.createObjectURL(file);
    setUrl(created);
    return () => URL.revokeObjectURL(created);
  }, [file]);

  const estimate = meta && Number.isFinite(meta.duration) ? approx(meta.duration * 20) : null;
  const ready = [
    { ok: !!file, text: "Video cargado" },
    { ok: !!style, text: "Estilo seleccionado" },
    { ok: true, text: `Temporada: ${season ?? "Sin temporada"}` },
    { ok: true, text: `Vestuario: ${wardrobe}` },
    { ok: true, text: `Análisis: ${analysis}` },
  ];

  return (
    <aside className={styles.aside}>
      <section className={styles.card}>
        <h2>
          Vista previa <Icon name="info" size={14} />
        </h2>
        <Segmented
          label="Vista previa"
          value={view}
          onChange={setView}
          options={[
            { id: "original", label: "Original" },
            // PENDIENTE(fase 2): la vista previa real "Con efectos" (§3.1 del análisis, por ventana).
            { id: "effects", label: "Con efectos", disabled: !file, title: file ? PREVIEW_WITH_EFFECTS_NOTE : "Carga un video primero" },
          ]}
        />
        <div className={styles.player}>
          {url ? (
            <>
              <video src={url} controls playsInline muted loop />
              {view === "effects" && style && (
                <>
                  {/* Muestra del estilo sobre tu video: no es el resultado, que se ve al terminar. */}
                  <NeonPreview palette={style.palette} seed={style.name.length * 7} active className={styles.overlay} />
                  <span className={styles.sample}>Muestra del estilo · el resultado real llega al terminar</span>
                </>
              )}
            </>
          ) : (
            <div className={styles.empty}>
              <Icon name="film" size={30} />
              <span>Carga un video para verlo aquí</span>
            </div>
          )}
        </div>
      </section>

      <section className={styles.card}>
        <h2>Información del video</h2>
        <Row label="Duración" value={meta && Number.isFinite(meta.duration) ? mmss(meta.duration) : "—"} />
        <Row label="Resolución" value={meta ? `${meta.width} × ${meta.height}` : "—"} />
        <Row label="Tamaño" value={file ? `${(file.size / 1e6).toFixed(1)} MB` : "—"} />
      </section>

      <section className={styles.card}>
        <h2>Resumen del proyecto</h2>
        <div className={styles.summary}>
          <div className={styles.cover} style={style?.palette[0] ? { background: `linear-gradient(135deg, ${rgb(style.palette[0], 0.5)}, ${rgb(style.palette[1] ?? style.palette[0], 0.2)})` } : undefined}>
            {url && <video src={url} muted playsInline />}
          </div>
          <div>
            <strong>{style ? style.title : "Sin estilo"}</strong>
            <span className={`${styles.badge} ${analysis === "Económico" ? "" : styles.deep}`}>{analysis}</span>
            {looks && <small>{looks}</small>}
          </div>
        </div>
        <ul className={styles.checks}>
          {ready.map((item) => (
            <li key={item.text} className={item.ok ? styles.ok : ""}>
              <Icon name="checkCircle" size={16} /> {item.text}
            </li>
          ))}
        </ul>
      </section>

      <section className={`${styles.card} ${styles.cta}`}>
        {upload !== null ? (
          <div className={styles.uploading}>
            <span className="mono">Subiendo {Math.round(upload * 100)}%</span>
            <div className={styles.bar}>
              <i style={{ width: `${upload * 100}%` }} />
            </div>
          </div>
        ) : (
          <Button icon="arrow" disabled={!canLaunch} onClick={onLaunch}>
            Crear mis efectos
          </Button>
        )}
        {error && (
          <p className={styles.error} role="alert">
            <Icon name="alert" size={16} /> {error}
          </p>
        )}
        <p className={styles.note}>Tiempo estimado: {estimate ?? "—"}</p>
        {/* PENDIENTE(fase 3): créditos reales; hoy un dato fijo del diseño. */}
        <p className={styles.credit}>
          <Icon name="clock" size={14} /> {PLAN.creditsPerRender} crédito
        </p>
      </section>
    </aside>
  );
}
