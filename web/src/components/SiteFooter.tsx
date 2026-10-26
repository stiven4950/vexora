import { Link } from "react-router-dom";

import { ROUTES } from "../routes";
import { Icon } from "./Icon";
import { Logo } from "./Logo";
import styles from "./SiteFooter.module.css";

/** Pie común de la landing y de la app: marca, eslogan, legales y redes. */
export function SiteFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.brand}>
        <Logo size={24} />
        <span>Tus movimientos. Tus poderes. Tu imaginación.</span>
      </div>
      <nav className={styles.links} aria-label="Legales">
        <Link to={ROUTES.terms}>Términos de uso</Link>
        <Link to={ROUTES.privacy}>Privacidad</Link>
        <Link to={ROUTES.support}>Soporte</Link>
      </nav>
      {/* PENDIENTE(fase 1b): las cuentas oficiales de redes. Hasta tenerlas, los íconos no enlazan. */}
      <div className={styles.social} aria-hidden="true">
        <Icon name="instagram" size={18} />
        <Icon name="youtube" size={18} />
        <Icon name="tiktok" size={18} />
        <Icon name="x" size={18} />
      </div>
    </footer>
  );
}
