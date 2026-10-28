import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";

import { useSession } from "../auth/AuthContext";
import { ago } from "../api/format";
import { useProfile } from "../auth/ProfileContext";
import { useNotifications } from "../hooks/useNotifications";
import { ROUTES } from "../routes";
import { AppSidebar } from "./AppSidebar";
import { Icon } from "./Icon";
import { Logo } from "./Logo";
import { SiteFooter } from "./SiteFooter";
import styles from "./Shell.module.css";

interface Props {
  children: ReactNode;
  /** Colores de la aurora de fondo (siguen al estilo elegido). */
  aurora?: [string, string];
  /** La barra lateral: la de la app por omisión, o la de un proyecto. */
  sidebar?: ReactNode;
  /** Pie de página (el diseño del Estudio lo muestra; los de proyecto, no). */
  footer?: boolean;
}

const TABS = [
  { to: ROUTES.studio, label: "Estudio" },
  { to: ROUTES.library, label: "Mis proyectos" },
  { to: ROUTES.explore, label: "Explorar efectos" },
  { to: ROUTES.plan, label: "Mi plan" },
];

/** Cierra un menú al hacer clic fuera. */
function useOutside(close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) close();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [close]);
  return ref;
}

function Bell() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { items, unread, markAllRead } = useNotifications();
  // Lo que estaba sin leer al abrir sigue resaltado mientras el menú está abierto.
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const ref = useOutside(() => setOpen(false));
  const toggle = () => {
    if (!open) {
      setFresh(new Set(items.filter((item) => !item.read).map((item) => item.id)));
      if (unread > 0) markAllRead();
    }
    setOpen((v) => !v);
  };
  return (
    <div className={styles.menuWrap} ref={ref}>
      <button type="button" className={styles.iconButton} onClick={toggle} aria-label={unread ? `Notificaciones (${unread} sin leer)` : "Notificaciones"} aria-expanded={open}>
        <Icon name="bell" size={22} />
        {unread > 0 && <i className={styles.dot} />}
      </button>
      {open && (
        <div className={styles.popover} role="menu">
          <strong>Notificaciones</strong>
          {items.length === 0 && <small className={styles.empty}>Aún no tienes avisos. Te avisamos cuando tus videos estén listos.</small>}
          {items.map((note) => (
            <button
              key={note.id}
              type="button"
              className={fresh.has(note.id) ? styles.unread : ""}
              onClick={() => {
                setOpen(false);
                if (note.job_id) navigate(ROUTES.job(note.job_id));
              }}
            >
              <span>{note.title}</span>
              <small>{note.text}</small>
              <small>{ago(note.created)}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const { user, signOut } = useSession();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useOutside(() => setOpen(false));
  const { profile } = useProfile();
  const name = profile?.display_name || user?.displayName || user?.email || "Invitado";
  const photo = profile?.avatar_url ?? user?.photoURL;
  return (
    <div className={styles.menuWrap} ref={ref}>
      <button type="button" className={styles.user} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {photo ? <img src={photo} alt="" referrerPolicy="no-referrer" /> : <span className={styles.initial}>{name.charAt(0).toUpperCase()}</span>}
        <span className={styles.name}>{name}</span>
        <Icon name="chevron" size={16} />
      </button>
      {open && (
        <div className={`${styles.popover} ${styles.right}`} role="menu">
          <button type="button" onClick={() => navigate(ROUTES.settings)}>
            <span>
              <Icon name="gear" size={16} /> Configuración
            </span>
          </button>
          <button type="button" onClick={() => void signOut()}>
            <span>
              <Icon name="logout" size={16} /> Salir
            </span>
          </button>
        </div>
      )}
    </div>
  );
}

/** El marco de toda la app: barra superior con pestañas, barra lateral y el contenido. */
export function Shell({ children, aurora, sidebar, footer = true }: Props) {
  const tint = aurora ? ({ "--aurora-a": aurora[0], "--aurora-b": aurora[1] } as CSSProperties) : undefined;
  const [drawer, setDrawer] = useState(false);
  return (
    <div className={styles.app}>
      <div className="aurora" style={tint} />
      <header className={styles.bar}>
        <button type="button" className={`${styles.iconButton} ${styles.burger}`} onClick={() => setDrawer((v) => !v)} aria-label="Menú" aria-expanded={drawer}>
          <Icon name="menu" size={22} />
        </button>
        <Link to={ROUTES.studio} className={styles.brand}>
          <Logo size={34} />
        </Link>
        <nav className={styles.tabs} aria-label="Secciones">
          {TABS.map((tab) => (
            <NavLink key={tab.to} to={tab.to} className={({ isActive }) => (isActive ? styles.on : "")}>
              {tab.label}
            </NavLink>
          ))}
        </nav>
        <div className={styles.tools}>
          <Bell />
          <UserMenu />
        </div>
      </header>
      <div className={styles.body}>
        <aside className={`${styles.side} ${drawer ? styles.open : ""}`} onClick={() => setDrawer(false)}>
          {sidebar ?? <AppSidebar />}
        </aside>
        <div className={styles.column}>
          <main className={styles.main}>{children}</main>
          {footer && <SiteFooter />}
        </div>
      </div>
    </div>
  );
}
