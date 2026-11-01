import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    // In development the API runs separately; proxying keeps the browser same-origin,
    // exactly as in production where FastAPI serves the built bundle.
    proxy: { "/api": "http://localhost:8000" },
  },
  test: {
    environment: "node",
  },
});
