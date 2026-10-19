import { defineConfig } from "cf/config";

export default defineConfig({
  worker: {
    name: "graph-hack",
    entrypoint: "./src/worker.ts",
    compatibilityDate: "2026-10-19",
    observability: {
      enabled: true
    }
  }
});
