import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { PublicVideo as PublicVideoData } from "../api/types";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import { SiteFooter } from "../components/SiteFooter";
import { ROUTES } from "../routes";
import styles from "./PublicVideo.module.css";

/** Un video compartido con enlace público: se ve sin iniciar sesión hasta que su dueño lo revoca. */
export function PublicVideo() {
  const { token = "" } = useParams();
  const [video, setVideo] = useState<PublicVideoData | null>(null);
  const [gone, setGone] = useState(false);
  // Límite de peticiones o de vistas de hoy (429): el enlace existe, solo hay que esperar.
  const [waitText, setWaitText] = useState<string | null>(null);

  useEffect(() => {
    // Un enlace compartido no debe aparecer en buscadores (el servidor también lo pide con X-Robots-Tag).
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex, nofollow";
    document.head.appendChild(meta);
    return () => meta.remove();
  }, []);

  useEffect(() => {
    let alive = true;
    api
      .publicVideo(token)
      .then((found) => alive && setVideo(found))
      .catch((cause: unknown) => {
        if (!alive) return;
        if (cause instanceof ApiError && cause.status === 429) setWaitText(cause.message);
        else setGone(true);
      });
    return () => {
      alive = false;
    };
  }, [token]);

  useEffect(() => {
    if (video) document.title = `${video.title} · VEXORA`;
  }, [video]);

  return (
    <div className={styles.page}>
      <div className="aurora" />
      <header className={styles.top}>
        <Link to={ROUTES.home} aria-label="Ir al inicio">
          <Logo size={30} />
        </Link>
        <Link to={ROUTES.register} className={styles.cta}>
          Probar VEXORA
        </Link>
      </header>
      <main className={styles.main}>
        {waitText && (
          <div className={styles.empty}>
            <Icon name="clock" size={28} />
            <h1>Vuelve en un rato</h1>
            <p>{waitText}</p>
          </div>
        )}
        {gone && (
          <div className={styles.empty}>
            <Icon name="alert" size={28} />
            <h1>Este enlace no está disponible</h1>
            <p>Puede que su dueño haya dejado de compartirlo o que el video ya no exista.</p>
            <Link to={ROUTES.home} className={styles.cta}>
              Conocer VEXORA
            </Link>
          </div>
        )}
        {!gone && !waitText && !video && <p className={styles.loading}>Cargando video…</p>}
        {video && (
          <>
            <video className={styles.player} src={video.video_url} controls playsInline preload="metadata" />
            <h1>{video.title}</h1>
            <p className={styles.meta}>
              Estilo {video.style_title}
              {video.duration ? ` · ${Math.round(video.duration)} s` : ""}
              {" · "}
              {new Date(video.created * 1000).toLocaleDateString("es", { day: "numeric", month: "long", year: "numeric" })}
            </p>
            <p className={styles.made}>
              <Icon name="sparkles" size={16} /> Creado con <strong>VEXORA</strong>
            </p>
            <section className={styles.invite}>
              <h2>Convierte tus videos en algo increíble</h2>
              <p>Sube un video y VEXORA le añade efectos que reaccionan a cada movimiento.</p>
              <Link to={ROUTES.register} className={styles.cta}>
                Crea el tuyo gratis <Icon name="arrow" size={16} />
              </Link>
            </section>
          </>
        )}
      </main>
      <SiteFooter />
    </div>
  );
}
