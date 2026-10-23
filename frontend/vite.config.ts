import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // The graph engine is large by nature. It loads lazily, only on screens that draw a graph.
    chunkSizeWarningLimit: 700,
  },
})
