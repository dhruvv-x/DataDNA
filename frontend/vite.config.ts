/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Where the backend listens, as seen from the machine that runs `npm run dev`.
  const backend = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'
  return {
    plugins: [react()],
    server: {
      // The browser talks only to Vite (one origin). Vite forwards "/api/..." to the backend, so the
      // login cookie works. Needs VITE_API_BASE=/api (frontend/.env.local) and COOKIE_PATH=/api/auth (.env).
      proxy: {
        '/api': {
          target: backend,
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/api/, ''),
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: false,
    },
  }
})
