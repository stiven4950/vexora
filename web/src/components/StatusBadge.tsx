import type { ProjectStatus } from "../api/format";
import styles from "./StatusBadge.module.css";

const LABEL: Record<ProjectStatus, string> = { done: "Completado", processing: "En proceso", failed: "Error" };

/** La insignia de estado de un proyecto: verde Completado, azul En proceso, rojo Error. */
export function StatusBadge({ status, className }: { status: ProjectStatus; className?: string }) {
  return <span className={`${styles.badge} ${styles[status]} ${className ?? ""}`}>{LABEL[status]}</span>;
}
