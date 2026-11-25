// /robots.txt: everything may be crawled once the site is live (see SITE_LIVE in lib/site.ts), and the sitemap address follows the `site` setting (so it changes with the domain).
// Pages that must stay out of Google carry a noindex tag instead; blocking them here would stop Google from ever seeing it.
import type { APIRoute } from "astro";
import { SITE_LIVE } from "../lib/site";

export const GET: APIRoute = ({ site }) => {
  // Before launch (PUBLIC_SITE_LIVE is not "true") everything is disallowed.
  if (!SITE_LIVE) {
    return new Response("User-agent: *\nDisallow: /\n", { headers: { "content-type": "text/plain; charset=utf-8" } });
  }
  const sitemap = new URL("sitemap-index.xml", site).href;
  return new Response(`User-agent: *\nAllow: /\n\nSitemap: ${sitemap}\n`, {
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
};
