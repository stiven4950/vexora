import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { NotificationPrefs, Preferences, Profile, ProfileChanges } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { useProfile } from "../auth/ProfileContext";
import background from "../assets/login/background-900.jpg";
import { Button } from "../components/Button";
import { Icon, type IconName } from "../components/Icon";
import { Logo } from "../components/Logo";
import { PromoCard } from "../components/PromoCard";
import { Shell } from "../components/Shell";
import { Toggle } from "../components/Toggle";
import { ROUTES } from "../routes";
import styles from "./Settings.module.css";

const BIO_MAX = 200;
const AVATAR_MAX_BYTES = 2 * 1024 * 1024;
const USERNAME = /^[a-z0-9_.]{3,30}$/;
const CONFIRM_WORD = "ELIMINAR";

const SECTIONS: { id: string; label: string; icon: IconName }[] = [
  { id: "perfil", label: "Perfil", icon: "gear" },
  { id: "seguridad", label: "Seguridad", icon: "shield" },
  { id: "notificaciones", label: "Notificaciones", icon: "bell" },
  { id: "preferencias", label: "Preferencias", icon: "filter" },
  { id: "facturacion", label: "Facturación", icon: "card" },
  { id: "dispositivos", label: "Dispositivos", icon: "devices" },
  { id: "privacidad", label: "Privacidad", icon: "lock" },
];

const NOTIFICATION_ROWS: { key: keyof NotificationPrefs; title: string; hint: string; icon: IconName }[] = [
  { key: "processing", title: "Procesamiento de videos", hint: "Te avisaremos cuando tus videos estén listos.", icon: "film" },
  { key: "platform", title: "Actualizaciones de la plataforma", hint: "Nuevas funciones, mejoras y mantenimiento.", icon: "refresh" },
  { key: "promotions", title: "Promociones y ofertas", hint: "Descuentos, planes y créditos especiales.", icon: "gift" },
];

function message(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

function Avatar({ url, name, className }: { url: string | null | undefined; name: string; className?: string }) {
  return url ? <img src={url} alt="" referrerPolicy="no-referrer" className={className} /> : <span className={className}>{name.charAt(0).toUpperCase()}</span>;
}

/** Una tarjeta de sección con su ícono, título y subtítulo (la columna derecha del diseño). */
function Panel({ id, icon, title, hint, children }: { id: string; icon: IconName; title: string; hint: string; children: ReactNode }) {
  return (
    <section id={id} className={styles.panel}>
      <header>
        <span className={styles.panelIcon}>
          <Icon name={icon} size={22} />
        </span>
        <div>
          <h2>{title}</h2>
          <small>{hint}</small>
        </div>
      </header>
      {children}
    </section>
  );
}

/** Una fila de un panel: ícono, texto y, a la derecha, su control. */
function Row({ id, icon, title, hint, children }: { id?: string; icon: IconName; title: string; hint?: ReactNode; children?: ReactNode }) {
  return (
    <div id={id} className={styles.row}>
      <span className={styles.rowIcon}>
        <Icon name={icon} size={20} />
      </span>
      <div className={styles.rowText}>
        <strong>{title}</strong>
        {hint && <small>{hint}</small>}
      </div>
      {children}
    </div>
  );
}

export function Settings() {
  const navigate = useNavigate();
  const { user, required, hasPassword, resetPassword, updateAuthProfile, deleteAuthUser, reauthenticate, signOut } = useSession();
  const { profile, setProfile, reload } = useProfile();
  const fileInput = useRef<HTMLInputElement>(null);

  const [form, setForm] = useState<{ name: string; username: string; country: string; bio: string } | null>(null);
  const [active, setActive] = useState("perfil");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [usernameError, setUsernameError] = useState<string | null>(null);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const [prefError, setPrefError] = useState<string | null>(null);
  const [passwordNote, setPasswordNote] = useState<string | null>(null);
  const [termsBusy, setTermsBusy] = useState(false);

  // El formulario arranca con lo guardado; después manda lo que la persona escribe.
  useEffect(() => {
    if (profile && form === null) setForm({ name: profile.display_name, username: profile.username ?? "", country: profile.country ?? "", bio: profile.bio });
  }, [profile, form]);

  const name = profile?.display_name || user?.displayName || user?.email || "Invitado";
  const email = profile?.email ?? user?.email ?? "";
  const photo = profile?.avatar_url ?? user?.photoURL ?? null;

  const goTo = (id: string) => {
    setActive(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // ----- perfil -----

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    const username = form.username.trim().replace(/^@/, "").toLowerCase();
    setFormError(null);
    setUsernameError(null);
    setSaved(false);
    if (!form.name.trim()) return setFormError("Escribe tu nombre.");
    if (username && !USERNAME.test(username)) return setUsernameError("De 3 a 30 caracteres: minúsculas, números, punto o guion bajo.");
    setSaving(true);
    try {
      const next = await api.updateMe({ display_name: form.name.trim(), username: username || null, country: form.country || null, bio: form.bio.trim() });
      setProfile(next);
      setForm({ name: next.display_name, username: next.username ?? "", country: next.country ?? "", bio: next.bio });
      // El nombre también vive en la sesión de Firebase (lo lee la barra superior y los correos).
      await updateAuthProfile({ displayName: next.display_name }).catch(() => undefined);
      setSaved(true);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) setUsernameError(cause.message);
      else setFormError(message(cause));
    } finally {
      setSaving(false);
    }
  };

  const chooseAvatar = async (file: File | undefined) => {
    if (!file) return;
    setAvatarError(null);
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return setAvatarError("La imagen debe ser JPG, PNG o WEBP.");
    if (file.size > AVATAR_MAX_BYTES) return setAvatarError("La imagen pesa más de 2 MB.");
    setAvatarBusy(true);
    try {
      setProfile(await api.uploadAvatar(file));
    } catch (cause) {
      setAvatarError(message(cause));
    } finally {
      setAvatarBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const removeAvatar = async () => {
    setAvatarError(null);
    setAvatarBusy(true);
    try {
      setProfile(await api.deleteAvatar());
      // Si había una foto de Google, también se quita del perfil de Firebase: el diseño dice "Eliminar".
      await updateAuthProfile({ photoURL: null }).catch(() => undefined);
    } catch (cause) {
      setAvatarError(message(cause));
    } finally {
      setAvatarBusy(false);
    }
  };

  // ----- avisos y preferencias: se guardan al instante -----

  const patch = async (changes: ProfileChanges, optimistic: (current: Profile) => Profile) => {
    if (!profile) return;
    setPrefError(null);
    setProfile(optimistic(profile));
    try {
      setProfile(await api.updateMe(changes));
    } catch (cause) {
      setProfile(profile);
      setPrefError(message(cause));
    }
  };

  const setNotification = (key: keyof NotificationPrefs, value: boolean) =>
    patch({ notifications: { [key]: value } }, (current) => ({ ...current, notifications: { ...current.notifications, [key]: value } }));

  const setPreference = <K extends keyof Preferences>(key: K, value: Preferences[K]) =>
    patch({ preferences: { [key]: value } }, (current) => ({ ...current, preferences: { ...current.preferences, [key]: value } }));

  // ----- seguridad -----

  const changePassword = async () => {
    setPasswordNote(null);
    if (!user) return setPasswordNote("En modo local no hay contraseña que cambiar.");
    if (!hasPassword) return setPasswordNote("Tu contraseña la administra el proveedor con el que entras (Google u otro). Cámbiala desde tu cuenta de ese proveedor.");
    try {
      await resetPassword(email);
      setPasswordNote(`Te enviamos un correo a ${email} para crear una contraseña nueva.`);
    } catch {
      setPasswordNote("No pudimos enviar el correo. Intenta de nuevo en un momento.");
    }
  };

  const acceptTerms = async () => {
    setTermsBusy(true);
    try {
      setProfile(await api.acceptTerms());
    } catch (cause) {
      setPrefError(message(cause));
    } finally {
      setTermsBusy(false);
    }
  };

  // ----- eliminar la cuenta -----

  const [confirm, setConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // La API ya borró los datos; Firebase pide haber entrado hace poco para borrar al usuario.
  const [needsLogin, setNeedsLogin] = useState(false);
  const [password, setPassword] = useState("");

  const finishDeletion = async () => {
    const result = await deleteAuthUser();
    if (result === "needs-login") {
      setNeedsLogin(true);
      return;
    }
    await signOut().catch(() => undefined);
    navigate(`${ROUTES.home}?inicio=1`, { replace: true });
  };

  const deleteAccount = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      if (!needsLogin) await api.deleteAccount(confirm);
      await finishDeletion();
    } catch (cause) {
      setDeleteError(message(cause));
    } finally {
      setDeleting(false);
    }
  };

  const reauthAndRetry = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await reauthenticate(hasPassword ? password : undefined);
      setNeedsLogin(false);
      await finishDeletion();
    } catch (cause) {
      setDeleteError(message(cause));
    } finally {
      setDeleting(false);
    }
  };

  // ----- vista -----

  if (!profile || !form) {
    return (
      <Shell footer={false}>
        <p className={styles.state}>{profile === null ? "Cargando tu perfil…" : ""}</p>
        <button type="button" className={styles.retry} onClick={() => void reload()}>
          Reintentar
        </button>
      </Shell>
    );
  }

  const countryName = profile.countries.find((c) => c.code === profile.country)?.name;
  const termsDate = profile.accepted_terms_at ? new Date(profile.accepted_terms_at * 1000).toLocaleDateString("es", { day: "numeric", month: "long", year: "numeric" }) : null;

  return (
    <Shell footer={false}>
      <header className={styles.banner} style={{ backgroundImage: `linear-gradient(90deg, rgba(8, 11, 20, 0.92) 25%, rgba(8, 11, 20, 0.25)), url(${background})` }}>
        <div>
          <h1>
            Configuración <span>de la cuenta</span>
          </h1>
          <p>Administra tu información, preferencias y seguridad.</p>
        </div>
        <Logo size={44} tagline className={styles.brand} />
      </header>

      <div className={styles.grid}>
        {/* ----- izquierda: quién eres y a dónde ir ----- */}
        <aside className={styles.left}>
          <div className={styles.me}>
            <div className={styles.avatarWrap}>
              <Avatar url={photo} name={name} className={styles.avatarBig} />
              <button type="button" className={styles.camera} onClick={() => fileInput.current?.click()} disabled={avatarBusy} aria-label="Cambiar imagen de perfil">
                <Icon name="upload" size={14} />
              </button>
            </div>
            <strong>{name}</strong>
            <small>{email}</small>
            <span className={styles.plan}>Plan {profile.plan.title}</span>
          </div>
          <nav className={styles.subnav} aria-label="Secciones de configuración">
            {SECTIONS.map((section) => (
              <button key={section.id} type="button" className={active === section.id ? styles.on : ""} onClick={() => goTo(section.id)}>
                <Icon name={section.icon} size={20} /> {section.label}
              </button>
            ))}
          </nav>
          <PromoCard title="Crea sin límites" text="Tu creatividad es la única frontera." cta="Ir al estudio" to={ROUTES.studio} />
        </aside>

        {/* ----- centro: perfil ----- */}
        <div className={styles.center}>
          <section id="perfil" className={styles.panel}>
            <h2 className={styles.title}>Información del perfil</h2>
            <small>Así te verán los demás en Vexora.</small>
            <form onSubmit={save} className={styles.form}>
              <label>
                <span>Nombre completo</span>
                <div className={styles.input}>
                  <Icon name="user" size={18} />
                  <input value={form.name} maxLength={60} onChange={(event) => setForm({ ...form, name: event.target.value })} autoComplete="name" />
                </div>
              </label>
              <label>
                <span>Correo electrónico</span>
                <div className={`${styles.input} ${styles.readonly}`}>
                  <Icon name="mail" size={18} />
                  <input value={email} readOnly aria-readonly="true" />
                </div>
              </label>
              <div className={styles.two}>
                <label>
                  <span>Nombre de usuario</span>
                  <div className={styles.input}>
                    <span className={styles.at}>@</span>
                    <input value={form.username} maxLength={31} onChange={(event) => setForm({ ...form, username: event.target.value })} autoComplete="username" placeholder="tu.usuario" aria-invalid={!!usernameError} />
                  </div>
                  {usernameError && <em role="alert">{usernameError}</em>}
                </label>
                <label>
                  <span>País / Región</span>
                  <div className={styles.input}>
                    <Icon name="explore" size={18} />
                    <select value={form.country} onChange={(event) => setForm({ ...form, country: event.target.value })}>
                      <option value="">Sin indicar</option>
                      {profile.countries.map((country) => (
                        <option key={country.code} value={country.code}>
                          {country.name}
                        </option>
                      ))}
                    </select>
                  </div>
                </label>
              </div>
              <label>
                <span>
                  Biografía <small>(opcional)</small>
                </span>
                <div className={styles.bio}>
                  <textarea value={form.bio} maxLength={BIO_MAX} rows={3} onChange={(event) => setForm({ ...form, bio: event.target.value })} />
                  <small>
                    {form.bio.length}/{BIO_MAX}
                  </small>
                </div>
              </label>
              {formError && <p className={styles.error} role="alert">{formError}</p>}
              <div className={styles.actions}>
                <Button type="submit" icon="check" disabled={saving}>
                  {saving ? "Guardando…" : "Guardar cambios"}
                </Button>
                {saved && <span className={styles.ok} role="status">Cambios guardados</span>}
              </div>
            </form>
          </section>

          <section className={styles.panel} id="imagen">
            <h2 className={styles.title}>Imagen de perfil</h2>
            <small>Recomendado: 512 × 512 px. Formatos: JPG, PNG, WEBP (hasta 2 MB).</small>
            <div className={styles.imageRow}>
              <Avatar url={photo} name={name} className={styles.avatarMid} />
              <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(event) => void chooseAvatar(event.target.files?.[0])} />
              <button type="button" className={styles.outline} onClick={() => fileInput.current?.click()} disabled={avatarBusy}>
                <Icon name="upload" size={16} /> {avatarBusy ? "Subiendo…" : "Cambiar imagen"}
              </button>
              <button type="button" className={`${styles.outline} ${styles.dangerOutline}`} onClick={() => void removeAvatar()} disabled={avatarBusy || !profile.avatar_url}>
                <Icon name="trash" size={16} /> Eliminar
              </button>
            </div>
            {avatarError && <p className={styles.error} role="alert">{avatarError}</p>}
          </section>

          <section id="privacidad" className={styles.panel}>
            <h2 className={styles.title}>Privacidad</h2>
            <small>Qué guardamos de ti y cómo lo manejamos.</small>
            <div className={styles.links}>
              <Link to={ROUTES.privacy}>
                Política de privacidad <Icon name="arrow" size={16} />
              </Link>
              <Link to={ROUTES.terms}>
                Términos del servicio <Icon name="arrow" size={16} />
              </Link>
            </div>
            <div className={styles.terms}>
              {profile.terms_current && termsDate ? (
                <small>Aceptaste los términos y la política de privacidad el {termsDate}.</small>
              ) : (
                <>
                  <small>{profile.accepted_terms_at ? "Cambiaron los términos o la privacidad: confírmalos de nuevo." : "Aún no has confirmado los términos ni la política de privacidad."}</small>
                  <button type="button" className={styles.outline} onClick={() => void acceptTerms()} disabled={termsBusy}>
                    <Icon name="check" size={16} /> Acepto los términos y la privacidad
                  </button>
                </>
              )}
            </div>

            <div className={styles.danger}>
              <h3>
                <Icon name="alert" size={18} /> Zona de peligro
              </h3>
              <p>
                Eliminar tu cuenta borra de forma permanente tu perfil y foto, todos tus videos y proyectos con sus versiones, tus subidas, los enlaces compartidos y tus avisos. No se puede deshacer.
              </p>
              {!needsLogin ? (
                <>
                  <label>
                    <span>
                      Escribe <b>{CONFIRM_WORD}</b> para confirmar
                    </span>
                    <input value={confirm} onChange={(event) => setConfirm(event.target.value)} autoComplete="off" spellCheck={false} />
                  </label>
                  <Button variant="danger" icon="trash" disabled={confirm !== CONFIRM_WORD || deleting} onClick={() => void deleteAccount()}>
                    {deleting ? "Eliminando…" : "Eliminar mi cuenta"}
                  </Button>
                </>
              ) : (
                <>
                  <p className={styles.warn}>
                    Tus datos ya se borraron. Por seguridad, Firebase pide que vuelvas a iniciar sesión para borrar también tu acceso.
                  </p>
                  {hasPassword && (
                    <label>
                      <span>Tu contraseña</span>
                      <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
                    </label>
                  )}
                  <Button variant="danger" icon="lock" disabled={deleting || (hasPassword && !password)} onClick={() => void reauthAndRetry()}>
                    {deleting ? "Confirmando…" : hasPassword ? "Confirmar y eliminar" : "Iniciar sesión de nuevo y eliminar"}
                  </Button>
                </>
              )}
              {deleteError && <p className={styles.error} role="alert">{deleteError}</p>}
            </div>
          </section>
        </div>

        {/* ----- derecha: seguridad, avisos y preferencias ----- */}
        <div className={styles.right}>
          <Panel id="seguridad" icon="shield" title="Seguridad" hint="Mantén tu cuenta protegida.">
            <Row icon="lock" title="Contraseña" hint={user ? (hasPassword ? "••••••••••" : "La administra tu proveedor de acceso (Google).") : "No disponible en modo local."}>
              <button type="button" className={styles.small} onClick={() => void changePassword()} disabled={!user && required}>
                Cambiar
              </button>
            </Row>
            {passwordNote && <p className={styles.note} role="status">{passwordNote}</p>}
            {/* PENDIENTE(fase 3): verificación en dos pasos (necesita Firebase Identity Platform con MFA). No se simula su estado. */}
            <Row icon="shield" title="Verificación en dos pasos" hint="Añade una capa extra de seguridad. Disponible pronto.">
              <Toggle checked={false} onChange={() => undefined} disabled label="Verificación en dos pasos (disponible pronto)" />
            </Row>
            {/* PENDIENTE(fase 3): sesiones activas y cierre remoto (necesita las APIs de administración de Firebase). */}
            <Row id="dispositivos" icon="devices" title="Sesiones activas" hint="Administra los dispositivos donde has iniciado sesión. Disponible pronto.">
              <button type="button" className={styles.small} disabled>
                Ver sesiones
              </button>
            </Row>
          </Panel>

          <Panel id="notificaciones" icon="bell" title="Notificaciones" hint="Configura qué tipo de notificaciones quieres recibir.">
            {NOTIFICATION_ROWS.map((row) => (
              <Row key={row.key} icon={row.icon} title={row.title} hint={row.hint}>
                <Toggle checked={profile.notifications[row.key]} onChange={(value) => void setNotification(row.key, value)} label={row.title} />
              </Row>
            ))}
          </Panel>

          <Panel id="preferencias" icon="filter" title="Preferencias" hint="Personaliza tu experiencia en Vexora.">
            <Row icon="explore" title="Idioma">
              <select className={styles.select} value={profile.preferences.language} onChange={(event) => void setPreference("language", event.target.value as Preferences["language"])} aria-label="Idioma">
                <option value="es">Español</option>
              </select>
            </Row>
            <Row icon="film" title="Calidad de vista previa" hint={profile.preferences.preview_quality === "rapida" ? "Menos píxeles: se generan más rápido." : undefined}>
              <select className={styles.select} value={profile.preferences.preview_quality} onChange={(event) => void setPreference("preview_quality", event.target.value as Preferences["preview_quality"])} aria-label="Calidad de vista previa">
                <option value="alta">Alta (recomendada)</option>
                <option value="rapida">Rápida</option>
              </select>
            </Row>
            <Row icon="sparkles" title="Tema">
              <select className={styles.select} value={profile.preferences.theme} onChange={(event) => void setPreference("theme", event.target.value as Preferences["theme"])} aria-label="Tema">
                <option value="oscuro">Oscuro</option>
              </select>
            </Row>
          </Panel>
          {prefError && <p className={styles.error} role="alert">{prefError}</p>}

          <Panel id="facturacion" icon="card" title="Facturación" hint="Tu plan, créditos y compras.">
            <Row icon="crown" title={`Plan ${profile.plan.title}`} hint={countryName ? `Cuenta en ${countryName}` : undefined}>
              <Link to={ROUTES.plan} className={styles.small}>
                Ir a Mi plan
              </Link>
            </Row>
          </Panel>
        </div>
      </div>
    </Shell>
  );
}
