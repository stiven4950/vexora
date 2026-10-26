import type { ReactNode } from "react";

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
}

/** Una opción de un solo clic con icono, nombre y, si hace falta, muestras de color. */
export function Tile({ selected, onSelect, icon, label, title, ribbon, swatches, small = false, disabled = false }: Props) {
  return (
    <button type="button" title={title} className={`${styles.tile} ${selected ? styles.on : ""} ${small ? styles.small : ""}`} onClick={onSelect} aria-pressed={selected} disabled={disabled}>
      {ribbon && <span className={styles.ribbon}>{ribbon}</span>}
      <span className={styles.icon}>{icon}</span>
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
