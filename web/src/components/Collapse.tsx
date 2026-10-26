import { useState, type ReactNode } from "react";

import { Icon } from "./Icon";
import styles from "./Collapse.module.css";

interface Props {
  title: string;
  /** Una línea con lo elegido, visible aunque esté plegado. */
  summary?: string;
  children: ReactNode;
}

/** Sección plegable: oculta lo opcional hasta que la persona lo pide, pero deja ver qué eligió. */
export function Collapse({ title, summary, children }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <section className={styles.box}>
      <button type="button" className={styles.head} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span>
          <strong>{title}</strong>
          {summary && !open && <small>{summary}</small>}
        </span>
        <span className={`${styles.chevron} ${open ? styles.up : ""}`}>
          <Icon name="chevron" size={18} />
        </span>
      </button>
      {open && <div className={styles.body}>{children}</div>}
    </section>
  );
}
