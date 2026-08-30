import { defineConfig } from 'vitest/config'

// Build output is committed so the Streamlit dashboard works without a Node
// toolchain. The directory is named `component/` (not `dist/`) because the
// repository .gitignore ignores dist/ and build/ globally.
export default defineConfig({
  base: './',
  build: {
    outDir: '../dashboard/components/workbench_frontend/component',
    emptyOutDir: true,
    target: 'es2020',
  },
  test: {
    environment: 'node',
    include: ['tests/**/*.test.ts'],
  },
})
