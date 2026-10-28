import { Link } from "react-router-dom";

import { Icon } from "../components/Icon";
import { Shell } from "../components/Shell";
import { ROUTES } from "../routes";
import styles from "./Placeholder.module.css";

interface Props {
  title: string;
  /** Qué fase del plan la construye (docs/analisis_mejoras_y_seguridad.md, §9). */
  phase: string;
  text: string;
}

/** Vista que está en el mapa de rutas pero aún no se construye: dice qué es y cuándo llega. */
export function Placeholder({ title, phase, text }: Props) {
  // PENDIENTE(fase indicada): reemplazar por la vista real.
  return (
    <Shell footer={false}>
      <section className={styles.box}>
        <Icon name="clock" size={32} />
        <span className="eyebrow">En desarrollo · {phase}</span>
        <h1>{title}</h1>
        <p>{text}</p>
        <Link to={ROUTES.studio} className={styles.link}>
          Ir al estudio <Icon name="arrow" size={16} />
        </Link>
      </section>
    </Shell>
  );
}
