import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API allows CORS from http://localhost:3000; the dev proxy avoids CORS
// entirely by serving /api from the same origin as the UI.
declare const process: { env: Record<string, string | undefined> }
const API_TARGET = process.env.SCENARIODB_API_TARGET ?? 'http://127.0.0.1:18000'

export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    port: 3000,
    host: 'localhost',
    proxy: { '/api': { target: API_TARGET, changeOrigin: true } },
  },
  preview: {
    port: 3000,
    proxy: { '/api': { target: API_TARGET, changeOrigin: true } },
  },
  build: { outDir: 'dist', target: 'es2020', chunkSizeWarningLimit: 2000 },
})
