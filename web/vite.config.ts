import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En desarrollo, /api va a la API de Python (vfxglow-api en el puerto 8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
});
