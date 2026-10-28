import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Style } from "../api/types";
import { HeroCompare } from "../components/HeroCompare";
import { Icon, type IconName } from "../components/Icon";
import { Logo } from "../components/Logo";
import { StyleEmblem } from "../components/StyleEmblem";
import { FEATURED_QUOTE, SHOW_PENDING, TESTIMONIALS } from "../mocks/pendientes";
import { useSession } from "../auth/AuthContext";
import { ROUTES } from "../routes";
import styles from "./Landing.module.css";

const BENEFITS: { icon: IconName; title: string; text: string }[] = [
  { icon: "wand", title: "Efectos únicos", text: "Elementos, atmósferas y estilos inspirados en la naturaleza, la fantasía y el arte visual." },
  { icon: "brain", title: "Inteligencia artificial", text: "Analiza tu video y selecciona los mejores momentos para crear un resultado impactante." },
  { icon: "bolt", title: "Rápido y fácil", text: "Sin conocimientos técnicos. Solo sube, elige, personaliza y deja que la magia suceda." },
  { icon: "share", title: "Comparte y sorprende", text: "Descarga tu video en alta calidad y compártelo con amigos o en tu proyecto." },
];

/** Los estilos que se destacan: los cinco elementos del catálogo, en este orden. */
const FEATURED = ["avatar", "fuego", "agua", "rayo", "tierra"];

/** La página pública: presenta VEXORA y lleva a crear el primer efecto. */
export function Landing() {
  const { user, required } = useSession();
  const signedIn = !required || !!user;
  const [styleList, setStyleList] = useState<Style[]>([]);
  useEffect(() => {
    api.styles().then(setStyleList).catch(() => setStyleList([]));
  }, []);
  const featured = FEATURED.map((name) => styleList.find((s) => s.name === name)).filter((s): s is Style => !!s);
  const start = signedIn ? ROUTES.studio : ROUTES.register;

  return (
    <div className={styles.page}>
      <div className="aurora" />
      <header className={styles.bar}>
        <Link to={ROUTES.home} className={styles.brand}>
          <Logo size={34} />
        </Link>
        <nav className={styles.nav} aria-label="Principal">
          <a href="#como">Cómo funciona</a>
          <a href="#estilos">Estilos</a>
          <a href="#ejemplos">Ejemplos</a>
          {/* PENDIENTE(fase 3): los precios existen cuando exista /app/plan; hasta entonces solo en desarrollo. */}
          {SHOW_PENDING && <Link to={ROUTES.plan}>Precios</Link>}
          <Link to={ROUTES.support}>Ayuda</Link>
        </nav>
        <div className={styles.cta}>
          {!signedIn && (
            <Link to={ROUTES.login} className={styles.ghost}>
              Iniciar sesión
            </Link>
          )}
          <Link to={start} className={styles.solid}>
            {signedIn ? "Ir al estudio" : "Crear mi primer efecto"}
          </Link>
        </div>
      </header>

      <section className={styles.hero}>
        <div className={styles.heroText}>
          <span className="eyebrow">Tu video, otro mundo</span>
          <h1>
            Convierte tus videos en experiencias visuales <span>extraordinarias</span>
          </h1>
          <p>
            VEXORA usa inteligencia artificial para aplicar efectos visuales inspirados en la naturaleza, los elementos y la imaginación. Sube tu video, elige un estilo y descubre lo que es posible.
          </p>
          <div className={styles.actions}>
            <Link to={start} className={styles.solid}>
              Crear mi primer efecto <Icon name="arrow" size={16} />
            </Link>
            <a href="#ejemplos" className={styles.link}>
              <span>
                <Icon name="play" size={12} />
              </span>
              Ver ejemplos
            </a>
          </div>
        </div>
        {/* PENDIENTE(fase 1b): reemplazar la ilustración por un antes/después real, con material propio o con licencia. */}
        <HeroCompare />
      </section>

      <section id="como" className={styles.benefits}>
        {BENEFITS.map((item) => (
          <div key={item.title}>
            <span className={styles.badge}>
              <Icon name={item.icon} size={26} />
            </span>
            <h3>{item.title}</h3>
            <p>{item.text}</p>
          </div>
        ))}
      </section>

      <section id="estilos" className={styles.featured}>
        <header>
          <div>
            <span className="eyebrow">Estilos destacados</span>
            <h2>Efectos para cada historia</h2>
            <p>Explora nuestros estilos y encuentra el perfecto para tu video. Desde la fuerza de los elementos hasta la magia de la fantasía.</p>
          </div>
          <Link to={start}>
            Ver todos los estilos <Icon name="arrow" size={14} />
          </Link>
        </header>
        <div className={styles.cards}>
          {featured.map((style) => (
            <Link key={style.name} to={start} className={styles.card}>
              <StyleEmblem style={style.name} active className={styles.art} />
              <span className={styles.cardText}>
                <strong>{style.title}</strong>
                <small>{style.subtitle}</small>
              </span>
            </Link>
          ))}
        </div>
      </section>

      <section id="ejemplos" className={styles.band}>
        <div className={styles.phone} aria-hidden="true">
          <HeroCompare />
        </div>
        <div className={styles.quotes}>
          <span className="eyebrow">{SHOW_PENDING ? "Lo que dicen nuestros usuarios" : "Hecho para creadores"}</span>
          {/* PENDIENTE(fase 3): testimonios reales con permiso. Inventados no se publican: solo con SHOW_PENDING. */}
          {SHOW_PENDING ? (
            <>
              <blockquote>
                “{FEATURED_QUOTE.quote}”
                <cite>
                  <b>{"★".repeat(FEATURED_QUOTE.stars)}</b> — {FEATURED_QUOTE.who}
                </cite>
              </blockquote>
              <div className={styles.more}>
                {TESTIMONIALS.map((t) => (
                  <blockquote key={t.who}>
                    “{t.quote}”<cite>— {t.who}</cite>
                  </blockquote>
                ))}
              </div>
            </>
          ) : (
            <blockquote>VEXORA convierte lo cotidiano en algo increíble. Es como tener un estudio de efectos visuales en el bolsillo.</blockquote>
          )}
        </div>
      </section>

      <section className={styles.final}>
        <h2>¿Listo para crear algo increíble?</h2>
        <p>Tu próxima gran creación está a un clic de distancia.</p>
        <Link to={start} className={styles.solid}>
          Crear mi primer efecto <Icon name="arrow" size={16} />
        </Link>
      </section>

      <footer className={styles.footer}>
        <div>
          <Logo size={26} />
          <small>Efectos visuales con inteligencia artificial.</small>
        </div>
        <nav aria-label="Pie">
          <a href="#como">Cómo funciona</a>
          <a href="#estilos">Estilos</a>
          <Link to={ROUTES.support}>Ayuda</Link>
        </nav>
        <div className={styles.legal}>
          <Link to={ROUTES.terms}>Términos de uso</Link>
          <Link to={ROUTES.privacy}>Política de privacidad</Link>
          <Link to={ROUTES.support}>Contacto</Link>
        </div>
      </footer>
    </div>
  );
}
