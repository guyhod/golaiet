import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built files are served by Django's static handling under /static/, so the
// built index.html references /static/assets/*. In dev, Vite serves the app on
// 5174 and proxies /api to the Django dev server.
export default defineConfig({
  plugins: [react()],
  base: "/static/",
  server: {
    port: 5174,
    proxy: { "/api": "http://127.0.0.1:8003" },
  },
});
