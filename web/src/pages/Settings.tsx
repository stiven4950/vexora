import { useState } from "react";

import { useSession } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { Shell } from "../components/Shell";
import { soonNotice } from "../mocks/pendientes";
import styles from "./Settings.module.css";

/** Configuración mínima: quién eres, si tu correo está verificado y cerrar sesión. */
export function Settings() {
  const { user, required, signOut, resendVerification } = useSession();
  const [sent, setSent] = useState(false);
  const name = user?.displayName ?? user?.email ?? "Invitado";

  const resend = async () => {
    try {
      await resendVerification();
      setSent(true);
    } catch {
      window.alert("No se pudo enviar el correo. Intenta de nuevo en un momento.");
    }
  };

  return (
    <Shell footer={false}>
      <header className={styles.head}>
        <h1>
          Configuración <span>de la cuenta</span>
        </h1>
        <p>Tu perfil y la seguridad de tu cuenta.</p>
      </header>

      <section className={styles.card}>
        <h2>Perfil</h2>
        <div className={styles.profile}>
          {user?.photoURL ? <img src={user.photoURL} alt="" referrerPolicy="no-referrer" /> : <span>{name.charAt(0).toUpperCase()}</span>}
          <div>
            <strong>{name}</strong>
            <small>{user?.email ?? (required ? "" : "Modo local: sin cuenta")}</small>
          </div>
        </div>
      </section>

      {user && (
        <section className={styles.card}>
          <h2>Seguridad</h2>
          <div className={styles.row}>
            <div>
              <strong>Correo electrónico</strong>
              <small>{user.emailVerified ? "Verificado" : "Sin verificar: confirma tu correo para recuperar tu cuenta y tus videos."}</small>
            </div>
            {!user.emailVerified && user.email && (
              <button type="button" onClick={resend} disabled={sent}>
                {sent ? "Correo enviado" : "Reenviar verificación"}
              </button>
            )}
            {user.emailVerified && (
              <span className={styles.ok}>
                <Icon name="checkCircle" size={18} />
              </span>
            )}
          </div>
          <div className={styles.row}>
            <div>
              <strong>Cerrar sesión</strong>
              <small>Sales de este navegador. Tus proyectos se quedan guardados.</small>
            </div>
            <button type="button" onClick={() => void signOut()}>
              <Icon name="logout" size={16} /> Salir
            </button>
          </div>
        </section>
      )}

      <section className={styles.card}>
        <h2>Tus datos</h2>
        <div className={styles.row}>
          <div>
            <strong>Eliminar mi cuenta y mis datos</strong>
            <small>Borra tu cuenta, tus videos, su análisis y los resultados.</small>
          </div>
          {/* PENDIENTE(fase 3): borrar la cuenta completa (hoy cada proyecto se borra desde Mis proyectos). */}
          <button type="button" className={styles.danger} onClick={() => soonNotice("Eliminar la cuenta")}>
            Eliminar
          </button>
        </div>
      </section>
    </Shell>
  );
}
