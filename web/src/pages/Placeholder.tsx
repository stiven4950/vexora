import { Link } from "react-router-dom";

import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
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

/** Página pública de un documento legal o de ayuda: el texto lo redacta el negocio. */
export function LegalPlaceholder({ title }: { title: string }) {
  // PENDIENTE(fase 1b): el texto legal (términos, privacidad, soporte) lo redacta el negocio.
  return (
    <div className={styles.legal}>
      <div className="aurora" />
      <Link to={ROUTES.home}>
        <Logo size={30} />
      </Link>
      <section className={styles.box}>
        <span className="eyebrow">Documento en preparación</span>
        <h1>{title}</h1>
        <p>Estamos redactando este documento. Si tienes dudas, escríbenos mientras tanto.</p>
        <Link to={ROUTES.home} className={styles.link}>
          <Icon name="back" size={16} /> Volver al inicio
        </Link>
      </section>
    </div>
  );
}
