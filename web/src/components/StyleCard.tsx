import { actionLabel, rgb } from "../api/format";
import type { Style } from "../api/types";
import { NeonPreview } from "./NeonPreview";
import styles from "./StyleCard.module.css";

interface Props {
  style: Style;
  selected: boolean;
  onSelect: () => void;
  compact?: boolean;
}

export function StyleCard({ style, selected, onSelect, compact = false }: Props) {
  const accent = style.palette[0] ? rgb(style.palette[0]) : "var(--cyan)";
  return (
    <button
      type="button"
      className={`${styles.card} ${selected ? styles.selected : ""} ${compact ? styles.compact : ""}`}
      style={{ ["--accent" as string]: accent }}
      onClick={onSelect}
      aria-pressed={selected}
    >
      {!compact && <NeonPreview palette={style.palette} seed={style.name.length * 7} active={selected} className={styles.canvas} />}
      <div className={styles.body}>
        <div className={styles.head}>
          <span className="eyebrow">{style.kind === "catalog" ? "Coreografía" : "Preset"}</span>
          <span className={styles.swatches}>
            {style.palette.slice(0, 6).map((color, index) => (
              <i key={index} style={{ background: rgb(color) }} />
            ))}
          </span>
        </div>
        <h3>{style.title}</h3>
        {!compact && <p>{style.description}</p>}
        {!compact && style.actions.length > 0 && (
          <div className={styles.tags}>
            {style.actions.slice(0, 5).map((action) => (
              <span key={action}>{actionLabel(action)}</span>
            ))}
            {style.actions.length > 5 && <span>+{style.actions.length - 5}</span>}
          </div>
        )}
      </div>
      <span className={styles.check} aria-hidden="true" />
    </button>
  );
}
