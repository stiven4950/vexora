import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { SessionProvider, useSession } from "./auth/AuthContext";
import { JobPage } from "./pages/JobPage";
import { Login } from "./pages/Login";
import { Library } from "./pages/Library";
import { Studio } from "./pages/Studio";

export function App() {
  return (
    <SessionProvider>
      <Gate />
    </SessionProvider>
  );
}

/** Sin sesión, la pantalla de entrada; mientras Firebase recupera la sesión guardada, nada. */
function Gate() {
  const { user, required } = useSession();
  if (required && user === undefined) return <div className="aurora" />;
  if (required && !user) return <Login />;
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Studio />} />
        <Route path="/jobs/:id" element={<JobPage />} />
        <Route path="/library" element={<Library />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
