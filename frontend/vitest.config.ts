/// <reference types="vitest/config" />
import { getViteConfig } from "astro/config";

export default getViteConfig({
  resolve: { conditions: ["browser"] },
  test: {
    environment: "happy-dom",
    include: ["tests/unit/**/*.test.ts"],
    globals: true,
    restoreMocks: true,
  },
});
