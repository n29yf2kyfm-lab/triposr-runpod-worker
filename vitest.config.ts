import { defineConfig } from "vitest/config";

// tests/ holds the vitest suites; pipeline/testing holds PLAYWRIGHT specs
// (browser acceptance tests) which vitest must not try to execute.
export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
  },
});
