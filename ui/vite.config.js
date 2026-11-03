import { defineConfig } from 'vite';
export default defineConfig({
  build: { rollupOptions: { input: { main: 'index.html', companion: 'companion.html' } } },
  server: { proxy: { '/api': 'http://127.0.0.1:8765', '/ws': { target: 'ws://127.0.0.1:8765', ws: true } } },
  // MediaPipe's WASM loader installs ModuleFactory with importScripts.
  worker: { format: 'iife' },
});
