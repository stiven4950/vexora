import { useState, type ReactNode } from "react";

import styles from "./Tile.module.css";

interface Props {
  selected: boolean;
  onSelect: () => void;
  icon?: ReactNode;
  label: string;
  title?: string;
  /** Cinta sobre la esquina ("De temporada"). */
  ribbon?: string;
  /** Muestras de color debajo. */
  swatches?: string[];
  /** Un tamaño más compacto (los looks). */
  small?: boolean;
  disabled?: boolean;
  /** Una ilustración en una franja arriba en vez del icono; `active` = elegida o con el cursor encima. */
  art?: (active: boolean) => ReactNode;
}

/** Una opción de un solo clic con icono, nombre y, si hace falta, muestras de color. */
export function Tile({ selected, onSelect, icon, label, title, ribbon, swatches, small = false, disabled = false, art }: Props) {
  const [hover, setHover] = useState(false);
  return (
    <button
      type="button"
      title={title}
      className={`${styles.tile} ${selected ? styles.on : ""} ${small ? styles.small : ""} ${art ? styles.withArt : ""}`}
      onClick={onSelect}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-pressed={selected}
      disabled={disabled}
    >
      {ribbon && <span className={styles.ribbon}>{ribbon}</span>}
      {art ? <span className={styles.art}>{art(selected || hover)}</span> : <span className={styles.icon}>{icon}</span>}
      <span className={styles.label}>{label}</span>
      {swatches && swatches.length > 0 && (
        <span className={styles.swatches}>
          {swatches.map((color, index) => (
            <i key={index} style={{ background: color }} />
          ))}
        </span>
      )}
    </button>
  );
}
