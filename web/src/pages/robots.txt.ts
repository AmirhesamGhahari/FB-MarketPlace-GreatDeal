// /robots.txt: everything may be crawled, and the sitemap address follows the `site` setting (so it changes with the domain).
// Pages that must stay out of Google carry a noindex tag instead; blocking them here would stop Google from ever seeing it.
import type { APIRoute } from "astro";

export const GET: APIRoute = ({ site }) => {
  const sitemap = new URL("sitemap-index.xml", site).href;
  return new Response(`User-agent: *\nAllow: /\n\nSitemap: ${sitemap}\n`, {
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
};
