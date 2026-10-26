import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import background from "../assets/login/background.jpg";
import backgroundSmall from "../assets/login/background-900.jpg";
import { useSession } from "../auth/AuthContext";
import { LogoMark } from "../components/Logo";
import { ROUTES } from "../routes";
import styles from "./Login.module.css";

export type Mode = "signin" | "register" | "reset";

const FEATURES: { icon: ReactNode; title: string; text: string }[] = [
  { icon: <SparkleIcon />, title: "Efectos automáticos", text: "Detecta acciones, decide y crea." },
  { icon: <BoltIcon />, title: "Edición sin complicaciones", text: "Carga, ajusta y exporta en minutos." },
  { icon: <ScreenIcon />, title: "Resultados profesionales", text: "Calidad cinematográfica, sin complicaciones." },
];

/** Pantalla de entrada: la marca y lo que hace VEXORA a la izquierda, el acceso a la derecha. */
export function Login({ mode }: { mode: Mode }) {
  const navigate = useNavigate();
  const { signInEmail, signInGoogle, signInGitHub, register, resetPassword, error, clearError } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setNotice(null);
    try {
      await action();
    } catch {
      // el mensaje ya lo puso la sesión
    } finally {
      setBusy(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (mode === "signin") void run(() => signInEmail(email, password, remember));
    if (mode === "register") void run(() => register(email, password));
    if (mode === "reset")
      void run(async () => {
        await resetPassword(email);
        setNotice("Te enviamos un correo para crear una contraseña nueva.");
      });
  };

  const switchTo = (next: Mode) => {
    clearError();
    setNotice(null);
    navigate({ signin: ROUTES.login, register: ROUTES.register, reset: ROUTES.forgot }[next]);
  };

  const copy = {
    signin: { title: "Bienvenido", subtitle: "Inicia sesión para continuar con VEXORA", action: "Iniciar sesión" },
    register: { title: "Crea tu cuenta", subtitle: "Empieza a darle más vida a tus videos", action: "Crear cuenta" },
    reset: { title: "Recupera tu acceso", subtitle: "Te enviaremos un correo para crear una contraseña nueva", action: "Enviar correo" },
  }[mode];

  return (
    <div className={styles.page}>
      <picture className={styles.backdrop} aria-hidden="true">
        <source media="(max-width: 720px)" srcSet={backgroundSmall} />
        <img src={background} alt="" />
      </picture>
      <div className={styles.shade} aria-hidden="true" />

      <main className={styles.layout}>
        <section className={styles.intro}>
          <div className={styles.brand}>
            <LogoMark size={52} className={styles.mark} />
            <div>
              <span className={styles.wordmark}>VEXORA</span>
              <span className={styles.tagline}>
                Tu video, con <em>más vida</em>
              </span>
            </div>
          </div>

          <h1 className={styles.headline}>
            Convierte tus videos
            <br />
            en algo <em>extraordinario</em>
          </h1>
          <p className={styles.lead}>Añade efectos visuales inteligentes, animaciones y glow a tus videos con el poder de la IA.</p>

          <ul className={styles.features}>
            {FEATURES.map((feature) => (
              <li key={feature.title}>
                <span className={styles.featureIcon}>{feature.icon}</span>
                <span>
                  <strong>{feature.title}</strong>
                  <small>{feature.text}</small>
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.card} aria-labelledby="login-title">
          <h2 id="login-title">{copy.title}</h2>
          <p className={styles.subtitle}>{copy.subtitle}</p>

          <form className={styles.form} onSubmit={submit} noValidate>
            <label className={styles.field}>
              <MailIcon />
              <input type="email" autoComplete="email" placeholder="Correo electrónico" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            {mode !== "reset" && (
              <label className={styles.field}>
                <LockIcon />
                <input
                  type={showPassword ? "text" : "password"}
                  autoComplete={mode === "register" ? "new-password" : "current-password"}
                  placeholder="Contraseña"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button type="button" className={styles.eye} onClick={() => setShowPassword((v) => !v)} aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}>
                  <EyeIcon open={showPassword} />
                </button>
              </label>
            )}

            <button type="submit" className={styles.primary} disabled={busy}>
              {busy ? "Un momento…" : copy.action}
              <ArrowIcon />
            </button>

            {mode === "signin" && (
              <div className={styles.row}>
                <label className={styles.check}>
                  <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                  <span />
                  Recordarme
                </label>
                <button type="button" className={styles.link} onClick={() => switchTo("reset")}>
                  ¿Olvidaste tu contraseña?
                </button>
              </div>
            )}
          </form>

          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}
          {notice && (
            <p className={styles.notice} role="status">
              {notice}
            </p>
          )}

          {mode !== "reset" && (
            <>
              <div className={styles.divider}>
                <span>o continúa con</span>
              </div>
              <div className={styles.providers}>
                <button type="button" onClick={() => void run(() => signInGoogle(remember))} disabled={busy}>
                  <GoogleIcon /> Continuar con Google
                </button>
                <button type="button" onClick={() => void run(() => signInGitHub(remember))} disabled={busy}>
                  <GitHubIcon /> Continuar con GitHub
                </button>
              </div>
            </>
          )}

          <p className={styles.switch}>
            {mode === "signin" ? (
              <>
                ¿No tienes una cuenta?{" "}
                <button type="button" className={styles.link} onClick={() => switchTo("register")}>
                  Regístrate
                </button>
              </>
            ) : (
              <>
                {mode === "register" ? "¿Ya tienes una cuenta? " : "¿La recordaste? "}
                <button type="button" className={styles.link} onClick={() => switchTo("signin")}>
                  Inicia sesión
                </button>
              </>
            )}
          </p>
        </section>
      </main>

      <footer className={styles.footer}>
        <span className={styles.footerBrand}>
          <LogoMark size={14} />
          <b>VEXORA</b>
          <span className={styles.version}>v{__APP_VERSION__}</span>
        </span>
        <nav>
          <Link to={ROUTES.terms}>Términos de servicio</Link>
          <Link to={ROUTES.privacy}>Política de privacidad</Link>
          <Link to={ROUTES.support}>Soporte</Link>
        </nav>
      </footer>
    </div>
  );
}

// ----- íconos de línea con brillo (el estilo del diseño) -----

function SparkleIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true">
      <path d="M10 3c.6 4.2 2.4 6.1 6.6 6.7-4.2.6-6 2.5-6.6 6.7-.6-4.2-2.4-6.1-6.6-6.7C7.6 9.1 9.4 7.2 10 3Z" />
      <path d="M18 14.5c.3 1.8 1 2.5 2.8 2.8-1.8.3-2.5 1-2.8 2.8-.3-1.8-1-2.5-2.8-2.8 1.8-.3 2.5-1 2.8-2.8Z" />
      <path d="M18.5 3.5v3M17 5h3" strokeLinecap="round" />
    </svg>
  );
}

function BoltIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true">
      <path d="M13.5 2.5 5 13.5h6l-1 8 8.5-11h-6l1-8Z" />
    </svg>
  );
}

function ScreenIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="4.5" width="18" height="13" rx="2.5" />
      <path d="M10 8.5v5l4.2-2.5L10 8.5Z" />
      <path d="M8 20.5h8" strokeLinecap="round" />
    </svg>
  );
}

function MailIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2.5" />
      <path d="m4 7 8 6 8-6" strokeLinejoin="round" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <rect x="4.5" y="10.5" width="15" height="10" rx="2.5" />
      <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

function EyeIcon({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="3" />
      {!open && <path d="M4 4l16 16" />}
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12h14m-6-6 6 6-6 6" />
    </svg>
  );
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 48 48" width="20" height="20" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">
      <path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.47.11-3.06 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.77.11 3.06.74.81 1.19 1.84 1.19 3.1 0 4.42-2.7 5.39-5.26 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z" />
    </svg>
  );
}
