import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { resolve } from 'node:path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // three.js/@react-three (the 3D factory twin) is inherently large and
    // isolated into its own vendor-three chunk — it only loads on the pages
    // that actually render the twin (Diagnose, Simulate), never on the
    // rest of the app. 1300kB accepts that one known, unavoidable chunk
    // without re-triggering a warning that no longer reflects reality (the
    // app's own code is now ~105kB, down from one 2.3MB bundle).
    chunkSizeWarningLimit: 1300,
    rollupOptions: {
      input: {
        landing: resolve(__dirname, 'index.html'),
        app: resolve(__dirname, 'app.html'),
      },
      output: {
        // Vendor libraries split from app code and from each other — they
        // change far less often than the app itself (better long-term
        // browser caching) and keep any one chunk from growing unbounded
        // as new pages are added. Paired with the route-level React.lazy()
        // splitting in App.tsx, which is the bigger win: these libraries
        // only load at all when a page that actually uses them is visited.
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined;
          if (id.includes('three') || id.includes('@react-three')) return 'vendor-three';
          if (id.includes('leaflet')) return 'vendor-leaflet';
          if (id.includes('recharts') || id.includes('d3-')) return 'vendor-charts';
          if (id.includes('react-markdown') || id.includes('remark') || id.includes('micromark') || id.includes('mdast') || id.includes('unist') || id.includes('hast')) return 'vendor-markdown';
          if (id.includes('framer-motion')) return 'vendor-motion';
          return undefined;
        },
      },
    },
  },
})
