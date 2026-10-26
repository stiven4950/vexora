import { Link } from "react-router-dom";

import { Icon } from "./Icon";
import { NeonPreview } from "./NeonPreview";
import styles from "./PromoCard.module.css";

interface Props {
  title: string;
  text: string;
  cta: string;
  to: string;
}

/** Tarjeta del pie de la barra lateral: una imagen viva, un mensaje y un botón con borde. */
export function PromoCard({ title, text, cta, to }: Props) {
  return (
    <aside className={styles.card}>
      <NeonPreview palette={[[0.25, 0.85, 1], [0.55, 0.4, 1]]} seed={11} active className={styles.art} />
      <div className={styles.body}>
        <h3>{title}</h3>
        <p>{text}</p>
        <Link to={to} className={styles.cta}>
          {cta} <Icon name="arrow" size={16} />
        </Link>
      </div>
    </aside>
  );
}
