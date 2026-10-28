import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { Profile } from "../api/types";
import { useSession } from "./AuthContext";

interface ProfileState {
  /** null mientras carga o sin API; la barra superior usa Firebase como respaldo. */
  profile: Profile | null;
  setProfile: (profile: Profile) => void;
  reload: () => Promise<void>;
}

const ProfileContext = createContext<ProfileState | null>(null);

/** El perfil de la cuenta (GET /api/me), compartido por la barra superior y Configuración. */
export function ProfileProvider({ children }: { children: ReactNode }) {
  const { user, required } = useSession();
  const [profile, setProfile] = useState<Profile | null>(null);
  const signedIn = !required || !!user;
  const uid = user?.uid ?? null;

  const reload = useCallback(async () => {
    try {
      setProfile(await api.me());
    } catch {
      setProfile(null);
    }
  }, []);

  useEffect(() => {
    if (signedIn) void reload();
    else setProfile(null);
  }, [signedIn, uid, reload]);

  return <ProfileContext.Provider value={{ profile, setProfile, reload }}>{children}</ProfileContext.Provider>;
}

export function useProfile(): ProfileState {
  const state = useContext(ProfileContext);
  if (!state) throw new Error("useProfile fuera de ProfileProvider");
  return state;
}
