import type { ReactNode } from "react";

import styles from "./StepCard.module.css";

interface Props {
  n: number;
  title: string;
  /** La línea que explica el paso. */
  note?: ReactNode;
  /** "(opcional)" junto al título. */
  optional?: boolean;
  /** Lo que va a la derecha del encabezado (p. ej. "Sorpréndeme con IA"). */
  action?: ReactNode;
  children?: ReactNode;
}

/** Un paso del Estudio: tarjeta con el número en un círculo cian, título, nota y contenido. */
export function StepCard({ n, title, note, optional = false, action, children }: Props) {
  return (
    <section className={styles.card}>
      <header>
        <span className={styles.num}>{n}</span>
        <div>
          <h2>
            {title} {optional && <small>(opcional)</small>}
          </h2>
          {note && <p>{note}</p>}
        </div>
        {action && <div className={styles.action}>{action}</div>}
      </header>
      {children && <div className={styles.body}>{children}</div>}
    </section>
  );
}
