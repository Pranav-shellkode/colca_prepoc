import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Force both @pipecat-ai/client-js and the bare "client-js" specifier used
      // internally by @pipecat-ai/client-react types to resolve to the same copy,
      // eliminating the "not assignable" type error.
      'client-js': path.resolve(__dirname, 'node_modules/@pipecat-ai/client-js/dist/index.js'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      // Proxy /ws to the FastAPI backend during dev
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/calls': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
