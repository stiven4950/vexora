import type { CSSProperties, ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { Icon } from "./Icon";
import styles from "./Shell.module.css";

interface Props {
  children: ReactNode;
  /** Colores de la aurora de fondo (siguen al estilo elegido). */
  aurora?: [string, string];
}

export function Shell({ children, aurora }: Props) {
  const tint = aurora ? ({ "--aurora-a": aurora[0], "--aurora-b": aurora[1] } as CSSProperties) : undefined;
  return (
    <>
      <div className="aurora" style={tint} />
      <header className={styles.bar}>
        <NavLink to="/" className={styles.brand}>
          <svg viewBox="0 0 64 32" width="44" height="22" aria-hidden="true">
            <path d="M4 26 C18 2 40 2 60 18" className={styles.logoStroke} />
          </svg>
          <span>
            VFX<b>Glow</b>
          </span>
        </NavLink>
        <nav className={styles.nav}>
          <NavLink to="/" end className={({ isActive }) => (isActive ? styles.active : "")}>
            <Icon name="spark" size={16} /> Estudio
          </NavLink>
          <NavLink to="/library" className={({ isActive }) => (isActive ? styles.active : "")}>
            <Icon name="grid" size={16} /> Biblioteca
          </NavLink>
        </nav>
      </header>
      <main className={styles.main}>{children}</main>
      <footer className={styles.footer}>
        <span className="mono">VFX GLOW · motor procedural · el plano original nunca se redibuja</span>
      </footer>
    </>
  );
}
