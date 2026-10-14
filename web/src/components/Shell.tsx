import type { CSSProperties, ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { useSession } from "../auth/AuthContext";

import { Icon } from "./Icon";
import { Logo } from "./Logo";
import styles from "./Shell.module.css";

interface Props {
  children: ReactNode;
  /** Colores de la aurora de fondo (siguen al estilo elegido). */
  aurora?: [string, string];
}

export function Shell({ children, aurora }: Props) {
  const { user, signOut } = useSession();
  const tint = aurora ? ({ "--aurora-a": aurora[0], "--aurora-b": aurora[1] } as CSSProperties) : undefined;
  return (
    <>
      <div className="aurora" style={tint} />
      <header className={styles.bar}>
        <NavLink to="/" className={styles.brand}>
          <Logo size={24} />
        </NavLink>
        <nav className={styles.nav}>
          <NavLink to="/" end className={({ isActive }) => (isActive ? styles.active : "")}>
            <Icon name="spark" size={16} /> Estudio
          </NavLink>
          <NavLink to="/library" className={({ isActive }) => (isActive ? styles.active : "")}>
            <Icon name="grid" size={16} /> Biblioteca
          </NavLink>
        </nav>
        {user && (
          <div className={styles.user}>
            {user.photoURL ? (
              <img src={user.photoURL} alt="" referrerPolicy="no-referrer" />
            ) : (
              <span className={styles.initial}>{(user.displayName ?? user.email ?? "?").charAt(0).toUpperCase()}</span>
            )}
            <span className={styles.name}>{user.displayName ?? user.email}</span>
            <button type="button" onClick={() => void signOut()}>
              Salir
            </button>
          </div>
        )}
      </header>
      <main className={styles.main}>{children}</main>
      <footer className={styles.footer}>
        <Logo size={18} tagline className={styles.footerLogo} />
        <span className="mono">Efectos visuales con IA · el plano original nunca se redibuja</span>
      </footer>
    </>
  );
}
