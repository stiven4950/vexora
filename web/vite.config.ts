import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En desarrollo, /api va a la API de Python (vfxglow-api en el puerto 8000).
export default defineConfig({
  plugins: [react()],
  // Versión de package.json, visible en el pie de la pantalla de entrada.
  define: { __APP_VERSION__: JSON.stringify(process.env.npm_package_version ?? "") },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
});
