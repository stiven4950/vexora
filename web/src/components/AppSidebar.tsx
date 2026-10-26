import { NavLink } from "react-router-dom";

import { ROUTES } from "../routes";
import { Icon, type IconName } from "./Icon";
import { PromoCard } from "./PromoCard";
import styles from "./Sidebar.module.css";

const ITEMS: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: ROUTES.home + "?inicio=1", label: "Inicio", icon: "home" },
  { to: ROUTES.studio, label: "Estudio", icon: "wand" },
  { to: ROUTES.library, label: "Mis proyectos", icon: "projects" },
  { to: ROUTES.explore, label: "Explorar efectos", icon: "explore" },
  { to: ROUTES.plan, label: "Mi plan", icon: "card" },
  { to: ROUTES.settings, label: "Configuración", icon: "gear" },
];

/** Barra lateral de la app (diseños de Estudio y Mis proyectos). */
export function AppSidebar() {
  return (
    <>
      <nav className={styles.menu} aria-label="Principal">
        {ITEMS.map((item) => (
          <NavLink key={item.label} to={item.to} className={({ isActive }) => `${styles.item} ${isActive && !item.to.includes("?") ? styles.active : ""}`}>
            <Icon name={item.icon} size={20} /> {item.label}
          </NavLink>
        ))}
      </nav>
      <div className={styles.foot}>
        <PromoCard title="Tu creatividad no tiene límites" text="Explora nuevos estilos, combina efectos y dale vida a tus ideas." cta="Ir al estudio" to={ROUTES.studio} />
      </div>
    </>
  );
}
