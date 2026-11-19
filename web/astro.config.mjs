// @ts-check
import { defineConfig } from 'astro/config';

import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';

// `npm run dev` only: in the browser the app asks for /_api/v1/... (see lib/api.ts); the dev server forwards that to the live
// API. Set API_PROXY_TARGET=http://localhost:8000 to use a local uvicorn instead (it has no /api prefix, because the
// deployed Lambda strips it). The path starts with an underscore because Astro answers 404 to any other path without a
// trailing slash before a proxy could see it.
const apiProxyTarget = process.env.API_PROXY_TARGET ?? 'https://d2sru9uf6gw4cs.cloudfront.net';
const localApi = apiProxyTarget.startsWith('http://localhost');

// https://astro.build/config
export default defineConfig({
  // Used for canonical links and the sitemap. Replace with the custom domain when there is one.
  site: 'https://d2sru9uf6gw4cs.cloudfront.net',

  // Every page is built as /path/index.html and linked as /path/ (one address per page, no duplicates).
  trailingSlash: 'always',

  // React is used only for interactive "islands" (the charts); everything else stays plain HTML.
  integrations: [react()],

  vite: {
    plugins: [tailwindcss()],
    // `npm run dev` only: without this, the dev server serves react-dom/client unprocessed and the chart islands fail to hydrate.
    optimizeDeps: { include: ['react-dom/client'] },
    server: {
      proxy: {
        '/_api': {
          target: apiProxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/_api/, localApi ? '' : '/api'),
        },
      },
    },
  },
});