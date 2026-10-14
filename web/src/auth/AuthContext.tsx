import { onAuthStateChanged, signInWithPopup, signInWithRedirect, signOut, type User } from "firebase/auth";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { auth, authConfigured, googleProvider } from "./firebase";

interface Session {
  /** null sin sesión; undefined mientras Firebase recupera la sesión guardada. */
  user: User | null | undefined;
  /** false si la web corre sin Firebase (desarrollo): no se pide sesión. */
  required: boolean;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  error: string | null;
}

const SessionContext = createContext<Session | null>(null);

const MESSAGES: Record<string, string> = {
  "auth/popup-closed-by-user": "Cerraste la ventana antes de terminar.",
  "auth/cancelled-popup-request": "Cerraste la ventana antes de terminar.",
  "auth/network-request-failed": "No hay conexión con Google. Revisa tu internet.",
  "auth/unauthorized-domain": "Este dominio no está autorizado en Firebase (Authentication → Settings → Authorized domains).",
  "auth/operation-not-allowed": "El ingreso con Google no está activado en Firebase (Authentication → Sign-in method).",
};

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(authConfigured ? undefined : null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => (auth ? onAuthStateChanged(auth, setUser) : undefined), []);

  const signIn = async () => {
    if (!auth) return;
    setError(null);
    try {
      await signInWithPopup(auth, googleProvider);
    } catch (cause) {
      const code = (cause as { code?: string }).code ?? "";
      // Navegadores que bloquean ventanas emergentes (algunos móviles): por redirección.
      if (code === "auth/popup-blocked" || code === "auth/operation-not-supported-in-this-environment") {
        await signInWithRedirect(auth, googleProvider);
        return;
      }
      setError(MESSAGES[code] ?? "No se pudo iniciar sesión. Intenta de nuevo.");
    }
  };

  const value: Session = {
    user,
    required: authConfigured,
    signIn,
    signOut: async () => {
      if (auth) await signOut(auth);
    },
    error,
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession fuera de SessionProvider");
  return session;
}
