import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'))

export default defineConfig({
  plugins: [react()],
  define: { 'import.meta.env.VITE_APP_VERSION': JSON.stringify(pkg.version) },
  server: {
    port: 5173,
    // `npm run dev` talks to a backend on :8000 (override with TARGETHUB_DEV_API).
    proxy: {
      '/api': { target: process.env.TARGETHUB_DEV_API || 'http://localhost:8000', changeOrigin: true, ws: true },
      '/web': { target: process.env.TARGETHUB_DEV_API || 'http://localhost:8000', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    exclude: ['e2e/**', 'node_modules/**'],
    setupFiles: './src/test/setup.ts',
  }
})
