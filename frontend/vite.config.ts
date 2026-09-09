/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // Pinned (not Vite's default 5173): that port collides with another
    // project on this machine. strictPort means "fail loudly" instead of
    // silently starting on a different port that nothing else expects.
    port: 5180,
    strictPort: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
