import { initializeApp } from "firebase/app";
import { GoogleAuthProvider, getAuth, type Auth } from "firebase/auth";

/** Configuración web de Firebase (web/.env.local; plantilla en web/.env.example). Es pública: va
 * en el navegador por diseño. Lo que protege los datos es la verificación en la API. */
const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY as string | undefined,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET as string | undefined,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID as string | undefined,
  appId: import.meta.env.VITE_FIREBASE_APP_ID as string | undefined,
};

/** Sin configuración la web no pide sesión (desarrollo con la API en VEXORA_AUTH=off). */
export const authConfigured = Boolean(config.apiKey && config.projectId);

export const auth: Auth | null = authConfigured ? getAuth(initializeApp(config)) : null;

export const googleProvider = new GoogleAuthProvider();
googleProvider.setCustomParameters({ prompt: "select_account" });

/** El ID token de la sesión actual (Firebase lo renueva solo), o null sin sesión. */
export async function idToken(): Promise<string | null> {
  return auth?.currentUser ? auth.currentUser.getIdToken() : null;
}
