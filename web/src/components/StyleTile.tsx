import { rgb } from "../api/format";
import type { Style } from "../api/types";
import { Icon } from "./Icon";
import { NeonPreview } from "./NeonPreview";
import styles from "./StyleTile.module.css";

interface Props {
  style: Style;
  selected: boolean;
  onSelect: () => void;
  /** Es el estilo que recomienda el análisis del video. */
  recommended?: boolean;
}

/** Un estilo del Estudio: su muestra viva, el título, la idea en una línea y sus etiquetas. */
export function StyleTile({ style, selected, onSelect, recommended = false }: Props) {
  const accent = style.palette[0] ? rgb(style.palette[0]) : "var(--cyan)";
  return (
    <button type="button" className={`${styles.tile} ${selected ? styles.on : ""}`} style={{ ["--accent" as string]: accent }} onClick={onSelect} aria-pressed={selected}>
      <NeonPreview palette={style.palette} seed={style.name.length * 7} active={selected} className={styles.art} />
      {selected && (
        <span className={styles.check}>
          <Icon name="check" size={14} />
        </span>
      )}
      {recommended && <span className={styles.badge}>Recomendado</span>}
      <span className={styles.text}>
        <strong>{style.title}</strong>
        <small>{style.kind === "preset" ? "Preset fijo" : style.subtitle || style.description.split(":")[0]}</small>
        {style.tags.length > 0 && (
          <span className={styles.tags}>
            {style.tags.slice(0, 3).map((tag) => (
              <i key={tag}>{tag.charAt(0).toUpperCase() + tag.slice(1)}</i>
            ))}
          </span>
        )}
      </span>
    </button>
  );
}
