/** Todas las rutas de la web en un solo sitio (docs/analisis_mejoras_y_seguridad.md, §9.4). */
export const ROUTES = {
  home: "/",
  login: "/login",
  register: "/register",
  forgot: "/forgot-password",
  terms: "/terms",
  privacy: "/privacy",
  support: "/support",
  studio: "/app/studio",
  library: "/app/library",
  explore: "/app/explore",
  plan: "/app/plan",
  settings: "/app/settings",
  job: (id: string): string => `/app/jobs/${id}`,
  project: (id: string): string => `/app/projects/${id}`,
  edit: (id: string): string => `/app/projects/${id}/edit`,
} as const;
