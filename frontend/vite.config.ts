import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5173,
    // 開發模式:/api 代理到後端。
    // Docker 內用服務名 api;本機直跑時設 VITE_API_PROXY=http://localhost:8000。
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY || 'http://api:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
