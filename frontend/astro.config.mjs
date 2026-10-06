// @ts-check
import sitemap from "@astrojs/sitemap";
import svelte from "@astrojs/svelte";
import { defineConfig } from "astro/config";

const site = process.env.SITE_URL ?? "https://downloader.example";

export default defineConfig({
  site,
  output: "static",
  trailingSlash: "never",
  build: {
    format: "file",
    // CSP `style-src 'self'`: ship CSS as files, never inline <style>.
    inlineStylesheets: "never",
  },
  integrations: [svelte(), sitemap()],
  vite: {
    // Workaround (Astro 7.3.6 + Rolldown): with CSS code splitting, styles of Svelte
    // components mounted only on the client were dropped from the production build
    // ("plugin-css assigns to bundle variable" warning). Verified via screenshots/E2E.
    build: { cssCodeSplit: false },
    server: {
      proxy: { "/api": process.env.API_URL ?? "http://127.0.0.1:8000" },
      fs: { allow: [".."] }, // reads ../backend/openapi.json (provider list)
    },
  },
});
