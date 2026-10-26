import type { ReactNode } from "react";

import { Icon, type IconName } from "./Icon";
import styles from "./ChoiceCard.module.css";

interface Props {
  selected: boolean;
  onSelect: () => void;
  icon: IconName;
  title: string;
  /** "+$": lo que cuesta, junto al título. */
  price?: string;
  text: ReactNode;
  disabled?: boolean;
  hint?: string;
}

/** Una de las dos opciones grandes de un paso (el tipo de análisis). */
export function ChoiceCard({ selected, onSelect, icon, title, price, text, disabled = false, hint }: Props) {
  return (
    <button type="button" className={`${styles.card} ${selected ? styles.on : ""}`} onClick={onSelect} aria-pressed={selected} disabled={disabled} title={hint}>
      <span className={styles.icon}>
        <Icon name={icon} size={26} />
      </span>
      <span className={styles.text}>
        <strong>
          {title} {price && <em>{price}</em>}
        </strong>
        <small>{text}</small>
      </span>
    </button>
  );
}
