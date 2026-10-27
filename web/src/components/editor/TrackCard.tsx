import { useState } from "react";

import { effectLabel } from "../../api/effectLabels";
import { isPermanent, type TrackChange } from "../../api/editing";
import { mmssd } from "../../api/format";
import type { EditorTrack } from "../../api/types";
import { Icon, type IconName } from "../Icon";
import styles from "./TrackCard.module.css";

/** Colores que se ofrecen para una pista (el primero, el suyo). */
const SWATCHES = ["#1e90ff", "#22d3ee", "#7dd3fc", "#a855f7", "#ec4899", "#ef4444", "#f59e0b", "#facc15", "#22c55e", "#ffffff"];

interface Props {
  track: EditorTrack;
  change: TrackChange | undefined;
  onChange: (change: TrackChange | null) => void;
}

/** Una pista en "Efectos activos": su rango, su color, si está encendida y su intensidad y tamaño. */
export function TrackCard({ track, change, onChange }: Props) {
  const [palette, setPalette] = useState(false);
  const [menu, setMenu] = useState(false);
  const on = !change?.off;
  const name = effectLabel(track.label);
  const color = change?.color ?? track.color;
  const set = (patch: TrackChange) => onChange({ ...(change ?? {}), ...patch });
  return (
    <article className={`${styles.card} ${on ? "" : styles.off}`}>
      <span className={styles.icon} style={{ color, borderColor: color, boxShadow: `0 0 16px ${color}55` }}>
        <Icon name={track.icon as IconName} size={22} />
      </span>
      <div className={styles.text}>
        <strong title={name}>{name}</strong>
        <small>
          {isPermanent(track.key) ? "Todo el video" : `${mmssd(track.start)} – ${mmssd(track.end)}`}
        </small>
      </div>
      <div className={styles.tools}>
        <span className={styles.menuWrap}>
          <button type="button" className={styles.dot} style={{ background: color }} onClick={() => setPalette((v) => !v)} aria-label={`Color de ${name}`} />
          {palette && (
            <div className={styles.pop} onMouseLeave={() => setPalette(false)}>
              <strong>Color</strong>
              <div className={styles.swatches}>
                {SWATCHES.map((swatch) => (
                  <button key={swatch} type="button" style={{ background: swatch }} className={swatch === color ? styles.picked : ""} onClick={() => set({ color: swatch })} aria-label={swatch} />
                ))}
              </div>
              <button type="button" className={styles.reset} onClick={() => set({ color: undefined })}>
                Color original
              </button>
            </div>
          )}
        </span>
        <button type="button" role="switch" aria-checked={on} className={`${styles.switch} ${on ? styles.switchOn : ""}`} onClick={() => set({ off: on })} aria-label={on ? `Apagar ${name}` : `Encender ${name}`}>
          <i />
        </button>
        <span className={styles.menuWrap}>
          <button type="button" className={styles.more} onClick={() => setMenu((v) => !v)} aria-label="Más opciones">
            <Icon name="more" size={16} />
          </button>
          {menu && (
            <div className={`${styles.pop} ${styles.right}`} onMouseLeave={() => setMenu(false)}>
              <label>
                Intensidad <b>{Math.round((change?.intensity ?? 1) * 100)}%</b>
                <input type="range" min={0.2} max={2} step={0.05} value={change?.intensity ?? 1} onChange={(event) => set({ intensity: Number(event.target.value) })} />
              </label>
              <label>
                Tamaño <b>{Math.round((change?.size ?? 1) * 100)}%</b>
                <input type="range" min={0.5} max={2} step={0.05} value={change?.size ?? 1} onChange={(event) => set({ size: Number(event.target.value) })} />
              </label>
              <button type="button" className={styles.reset} onClick={() => onChange(null)}>
                Restablecer pista
              </button>
            </div>
          )}
        </span>
      </div>
    </article>
  );
}
