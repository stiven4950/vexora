import { Link, NavLink } from "react-router-dom";

import { ROUTES } from "../routes";
import { Icon, type IconName } from "./Icon";
import { PromoCard } from "./PromoCard";
import styles from "./Sidebar.module.css";

export type ProjectSection = "summary" | "edit" | "versions" | "processing" | "result" | "download";

interface Props {
  projectId: string;
  title: string;
  /** "23 oct 2026 · 02:14 p. m." */
  when: string;
  thumbnail?: string | null;
  /** La sección que corresponde a esta pantalla (la activa). */
  active: ProjectSection;
  /** "processing" solo cuando el trabajo está en curso; "result" cuando terminó. */
  state: "processing" | "result";
  onRename?: () => void;
  onDownload?: () => void;
}

/** Barra lateral de un proyecto (diseños del editor y de "en proceso"): su ficha y su menú. */
export function ProjectSidebar({ projectId, title, when, thumbnail, active, state, onRename, onDownload }: Props) {
  const items: { key: ProjectSection; label: string; icon: IconName; to?: string; onClick?: () => void; hide?: boolean }[] = [
    { key: "summary", label: "Resumen", icon: "summary", to: ROUTES.project(projectId) },
    { key: "edit", label: "Editar efectos", icon: "wand", to: ROUTES.edit(projectId) },
    { key: "versions", label: "Versiones", icon: "layers", to: `${ROUTES.project(projectId)}/versions` },
    { key: "processing", label: "Procesando", icon: "clock", hide: state !== "processing" },
    { key: "result", label: "Resultado", icon: "checkCircle", hide: state !== "result" },
    { key: "download", label: "Descargar", icon: "download", onClick: onDownload },
  ];
  return (
    <>
      <Link to={ROUTES.library} className={styles.back}>
        <Icon name="back" size={16} /> Volver a mis proyectos
      </Link>
      <div className={styles.project}>
        {thumbnail ? <img src={thumbnail} alt="" /> : <span className={styles.noThumb} />}
        <div>
          <strong title={title}>{title}</strong>
          {onRename && (
            <button type="button" onClick={onRename} className={styles.rename} aria-label="Renombrar">
              <Icon name="edit" size={14} />
            </button>
          )}
          <span className="mono">{when}</span>
        </div>
      </div>
      <nav className={styles.menu} aria-label="Proyecto">
        {items
          .filter((item) => !item.hide)
          .map((item) =>
            item.to ? (
              // PENDIENTE(fase 2): Resumen, Editar y Versiones del proyecto aún no existen: el enlace
              // es el del diseño y la ruta muestra "en desarrollo".
              <NavLink key={item.key} to={item.to} className={`${styles.item} ${active === item.key ? styles.active : ""}`}>
                <Icon name={item.icon} size={20} /> {item.label}
              </NavLink>
            ) : (
              <button key={item.key} type="button" onClick={item.onClick} className={`${styles.item} ${active === item.key ? styles.active : ""}`} disabled={!item.onClick && item.key === "download"}>
                <Icon name={item.icon} size={20} /> {item.label}
              </button>
            ),
          )}
      </nav>
      <div className={styles.foot}>
        <PromoCard title="Tu movimiento, convertido en poder" text="Efectos visuales con IA que reaccionan a cada gesto." cta="Ver más ejemplos" to={ROUTES.explore} />
      </div>
    </>
  );
}
