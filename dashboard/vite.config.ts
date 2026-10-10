import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build is served from its own nginx container (see Dockerfile), which
// proxies /api to Django. In dev, Vite serves the app on 5174 and proxies /api
// to the Django dev server on 8003.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: { "/api": "http://127.0.0.1:8003" },
  },
});
