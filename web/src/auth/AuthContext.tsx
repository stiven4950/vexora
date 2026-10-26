import {
  browserLocalPersistence,
  browserSessionPersistence,
  createUserWithEmailAndPassword,
  GithubAuthProvider,
  onAuthStateChanged,
  sendEmailVerification,
  sendPasswordResetEmail,
  setPersistence,
  signInWithEmailAndPassword,
  signInWithPopup,
  signInWithRedirect,
  signOut,
  type AuthProvider,
  type User,
} from "firebase/auth";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { auth, authConfigured, googleProvider } from "./firebase";

const githubProvider = new GithubAuthProvider();

interface Session {
  /** null sin sesión; undefined mientras Firebase recupera la sesión guardada. */
  user: User | null | undefined;
  /** false si la web corre sin Firebase (desarrollo): no se pide sesión. */
  required: boolean;
  /** remember: la sesión sigue al cerrar el navegador (si no, dura lo que la pestaña). */
  signInGoogle: (remember?: boolean) => Promise<void>;
  signInGitHub: (remember?: boolean) => Promise<void>;
  signInEmail: (email: string, password: string, remember?: boolean) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  resetPassword: (email: string) => Promise<void>;
  /** Vuelve a enviar el correo de verificación al usuario actual. */
  resendVerification: () => Promise<void>;
  signOut: () => Promise<void>;
  error: string | null;
  clearError: () => void;
}

const SessionContext = createContext<Session | null>(null);

const MESSAGES: Record<string, string> = {
  "auth/popup-closed-by-user": "Cerraste la ventana antes de terminar.",
  "auth/cancelled-popup-request": "Cerraste la ventana antes de terminar.",
  "auth/network-request-failed": "No hay conexión. Revisa tu internet.",
  "auth/unauthorized-domain": "Este dominio no está autorizado en Firebase (Authentication → Settings → Authorized domains).",
  "auth/operation-not-allowed": "Esta forma de entrar no está activada en Firebase (Authentication → Sign-in method).",
  "auth/invalid-credential": "Correo o contraseña incorrectos.",
  "auth/wrong-password": "Correo o contraseña incorrectos.",
  "auth/user-not-found": "Correo o contraseña incorrectos.",
  "auth/invalid-email": "Ese correo no es válido.",
  "auth/missing-password": "Escribe tu contraseña.",
  "auth/weak-password": "La contraseña debe tener al menos 6 caracteres.",
  "auth/email-already-in-use": "Ya existe una cuenta con ese correo. Inicia sesión.",
  "auth/too-many-requests": "Demasiados intentos. Espera un momento y vuelve a probar.",
  "auth/account-exists-with-different-credential": "Ese correo ya entra con otro método (por ejemplo, Google). Úsalo para entrar.",
  "auth/missing-email": "Escribe tu correo.",
};

function message(cause: unknown, fallback: string): string {
  const code = (cause as { code?: string }).code ?? "";
  return MESSAGES[code] ?? fallback;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(authConfigured ? undefined : null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => (auth ? onAuthStateChanged(auth, setUser) : undefined), []);

  const remember = async (keep: boolean) => {
    if (auth) await setPersistence(auth, keep ? browserLocalPersistence : browserSessionPersistence);
  };

  const withProvider = async (provider: AuthProvider, keep: boolean) => {
    if (!auth) return;
    setError(null);
    try {
      await remember(keep);
      await signInWithPopup(auth, provider);
    } catch (cause) {
      const code = (cause as { code?: string }).code ?? "";
      // Navegadores que bloquean ventanas emergentes (algunos móviles): por redirección.
      if (code === "auth/popup-blocked" || code === "auth/operation-not-supported-in-this-environment") {
        await signInWithRedirect(auth, provider);
        return;
      }
      setError(message(cause, "No se pudo iniciar sesión. Intenta de nuevo."));
    }
  };

  const value: Session = {
    user,
    required: authConfigured,
    signInGoogle: (keep = true) => withProvider(googleProvider, keep),
    signInGitHub: (keep = true) => withProvider(githubProvider, keep),
    signInEmail: async (email, password, keep = true) => {
      if (!auth) return;
      setError(null);
      try {
        await remember(keep);
        await signInWithEmailAndPassword(auth, email.trim(), password);
      } catch (cause) {
        setError(message(cause, "No se pudo iniciar sesión. Intenta de nuevo."));
      }
    },
    register: async (email, password) => {
      if (!auth) return;
      setError(null);
      try {
        await remember(true);
        const created = await createUserWithEmailAndPassword(auth, email.trim(), password);
        // Sin verificar, el correo no prueba que sea suyo (la API lo exige para adoptar trabajos viejos).
        await sendEmailVerification(created.user).catch(() => undefined);
      } catch (cause) {
        setError(message(cause, "No se pudo crear la cuenta. Intenta de nuevo."));
      }
    },
    resetPassword: async (email) => {
      if (!auth) return;
      setError(null);
      await sendPasswordResetEmail(auth, email.trim()).catch((cause: unknown) => {
        setError(message(cause, "No se pudo enviar el correo. Intenta de nuevo."));
        throw cause;
      });
    },
    resendVerification: async () => {
      if (auth?.currentUser) await sendEmailVerification(auth.currentUser);
    },
    signOut: async () => {
      if (auth) await signOut(auth);
    },
    error,
    clearError: () => setError(null),
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession fuera de SessionProvider");
  return session;
}
