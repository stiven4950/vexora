import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { JobPage } from "./pages/JobPage";
import { Library } from "./pages/Library";
import { Studio } from "./pages/Studio";

export function App() {
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
