// @ts-check
import { defineConfig } from 'astro/config';

import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';

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
  },
});