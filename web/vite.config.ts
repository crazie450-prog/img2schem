import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies the API to `img2schem serve` (port 8765); `npm run build` writes the bundle the Python
// package serves (img2schem/server/static), so running the UI needs no Node.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../img2schem/server/static", emptyOutDir: true, chunkSizeWarningLimit: 2000 },
  server: { proxy: { "/api": { target: "http://127.0.0.1:8765", ws: true } } },
});
