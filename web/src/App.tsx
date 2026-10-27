import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, useParams, useSearchParams } from "react-router-dom";

import { SessionProvider, useSession } from "./auth/AuthContext";
import { Editor } from "./pages/Editor";
import { JobPage } from "./pages/JobPage";
import { Landing } from "./pages/Landing";
import { Library } from "./pages/Library";
import { Login } from "./pages/Login";
import { LegalPlaceholder, Placeholder } from "./pages/Placeholder";
import { Settings } from "./pages/Settings";
import { Studio } from "./pages/Studio";
import { ROUTES } from "./routes";

export function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </SessionProvider>
  );
}

/** Las rutas viejas siguen abriendo: un enlace guardado o un aviso ya enviado no se rompe. */
function LegacyJob() {
  const { id } = useParams();
  return <Navigate to={id ? ROUTES.job(id) : ROUTES.library} replace />;
}

/** Con sesión (o sin Firebase, en desarrollo) deja pasar; si no, al acceso y de vuelta después. */
function RequireAuth({ authed }: { authed: boolean }) {
  const location = useLocation();
  return authed ? <Outlet /> : <Navigate to={ROUTES.login} replace state={{ from: location.pathname + location.search }} />;
}

/** Quien ya tiene sesión no vuelve a ver el acceso: va a donde iba o al estudio. */
function GuestOnly({ authed, children }: { authed: boolean; children: ReactNode }) {
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from;
  return authed ? <Navigate to={from ?? ROUTES.studio} replace /> : children;
}

/** La portada es para quien no ha entrado; con sesión se va directo al estudio (salvo con ?inicio=1). */
function Home({ authed }: { authed: boolean }) {
  const [params] = useSearchParams();
  return authed && !params.has("inicio") ? <Navigate to={ROUTES.studio} replace /> : <Landing />;
}

function AppRoutes() {
  const { user, required } = useSession();
  // Mientras Firebase recupera la sesión guardada, nada: así no parpadea el acceso.
  if (required && user === undefined) return <div className="aurora" />;
  const authed = !required || !!user;
  return (
    <Routes>
      <Route path={ROUTES.home} element={<Home authed={authed} />} />
      <Route path={ROUTES.login} element={<GuestOnly authed={authed}><Login mode="signin" /></GuestOnly>} />
      <Route path={ROUTES.register} element={<GuestOnly authed={authed}><Login mode="register" /></GuestOnly>} />
      <Route path={ROUTES.forgot} element={<GuestOnly authed={authed}><Login mode="reset" /></GuestOnly>} />
      <Route path={ROUTES.terms} element={<LegalPlaceholder title="Términos de uso" />} />
      <Route path={ROUTES.privacy} element={<LegalPlaceholder title="Política de privacidad" />} />
      <Route path={ROUTES.support} element={<LegalPlaceholder title="Soporte y ayuda" />} />
      <Route path="/app" element={<RequireAuth authed={authed} />}>
        <Route index element={<Navigate to={ROUTES.studio} replace />} />
        <Route path="studio" element={<Studio />} />
        <Route path="jobs/:id" element={<JobPage />} />
        <Route path="library" element={<Library />} />
        <Route path="explore" element={<Placeholder title="Explorar efectos" phase="fase 2" text="Una galería de cada estilo y efecto con videos de demostración." />} />
        <Route path="plan" element={<Placeholder title="Mi plan" phase="fase 3" text="Tu plan, tus créditos y tu consumo." />} />
        <Route path="settings" element={<Settings />} />
        <Route path="projects/:id/edit" element={<Editor />} />
        <Route path="projects/:id/*" element={<Placeholder title="Proyecto" phase="fase 2" text="El resumen y las versiones de tu video." />} />
      </Route>
      <Route path="/jobs/:id" element={<LegacyJob />} />
      <Route path="/library" element={<Navigate to={ROUTES.library} replace />} />
      <Route path="*" element={<Navigate to={ROUTES.home} replace />} />
    </Routes>
  );
}
