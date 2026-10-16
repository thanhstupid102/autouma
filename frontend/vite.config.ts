/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

const backend = 'http://127.0.0.1:1616'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  build: { assetsDir: 'static' },
  server: {
    proxy: Object.fromEntries(
      ['/api', '/races', '/assets/data', '/broom.png', '/sweep.png'].map(p => [p, { target: backend, changeOrigin: true }])
    ),
  },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test/setup.ts'] },
})
