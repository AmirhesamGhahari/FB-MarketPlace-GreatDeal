// Checks the BUILT site in dist/ (run `npm run build` first, then `npm run check:site`). Exits with an error when something
// that matters for search engines or visitors is wrong:
//   - an internal link or the sitemap points at a page that does not exist
//   - an indexable page lacks a title, a description, a canonical address, or has not exactly one <h1>
//   - a noindex page is listed in the sitemap, or an indexable page is missing from it
// Long titles and descriptions are only reported as warnings.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

const DIST = "dist";
if (!existsSync(DIST)) {
  console.error("dist/ not found: run `npm run build` first.");
  process.exit(1);
}

function htmlFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return htmlFiles(path);
    return name.endsWith(".html") ? [path] : [];
  });
}

// dist/iphone/index.html -> /iphone/ ; dist/404.html -> /404/
function pathnameOf(file) {
  const rel = relative(DIST, file).split(sep).join("/");
  if (rel === "index.html") return "/";
  if (rel.endsWith("/index.html")) return `/${rel.slice(0, -"index.html".length)}`;
  return `/${rel.replace(/\.html$/, "")}/`;
}

const pages = htmlFiles(DIST).map((file) => ({ file, pathname: pathnameOf(file), html: readFileSync(file, "utf8") }));
const known = new Set(pages.map((page) => page.pathname));
const errors = [];
const warnings = [];

const first = (html, pattern) => html.match(pattern)?.[1];
const sitemapFiles = existsSync(DIST) ? readdirSync(DIST).filter((name) => /^sitemap-\d+\.xml$/.test(name)) : [];
const sitemapPaths = new Set(
  sitemapFiles.flatMap((name) =>
    [...readFileSync(join(DIST, name), "utf8").matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => new URL(m[1]).pathname),
  ),
);
if (sitemapFiles.length === 0) errors.push("sitemap: no sitemap-N.xml in dist/");

for (const { pathname, html } of pages) {
  const noindex = /<meta name="robots" content="[^"]*noindex/.test(html);
  const isError = pathname === "/404/";

  // Internal links must lead somewhere.
  for (const [, href] of html.matchAll(/href="(\/[^"#?]*)/g)) {
    if (href.startsWith("//")) continue;
    const hasExtension = /\.[a-z0-9]+$/i.test(href);
    const ok = hasExtension ? existsSync(join(DIST, href)) : known.has(href.endsWith("/") ? href : `${href}/`);
    if (!ok) errors.push(`${pathname}: broken internal link ${href}`);
  }

  // Sitemap rules.
  if (noindex && sitemapPaths.has(pathname)) errors.push(`${pathname}: is noindex but listed in the sitemap`);
  if (!noindex && !isError && !sitemapPaths.has(pathname)) errors.push(`${pathname}: indexable page missing from the sitemap`);

  if (noindex || isError) continue;

  // Basics of an indexable page.
  const title = first(html, /<title>([^<]*)<\/title>/);
  const description = first(html, /<meta name="description" content="([^"]*)"/);
  const canonical = first(html, /<link rel="canonical" href="([^"]*)"/);
  const h1Count = (html.match(/<h1[\s>]/g) ?? []).length;
  if (!title) errors.push(`${pathname}: no <title>`);
  else if (title.length > 60) warnings.push(`${pathname}: title is ${title.length} characters (Google shows about 60)`);
  if (!description) errors.push(`${pathname}: no meta description`);
  else if (description.length > 160) warnings.push(`${pathname}: description is ${description.length} characters (Google shows about 155)`);
  else if (description.length < 50) warnings.push(`${pathname}: description is only ${description.length} characters`);
  if (/[{}]/.test(`${title}${description}`)) errors.push(`${pathname}: unfilled {placeholder} in the title or description`);
  if (html.includes("Great Deals")) errors.push(`${pathname}: still mentions the old name "Great Deals"`);
  if (!canonical) errors.push(`${pathname}: no canonical link`);
  else if (new URL(canonical).pathname !== pathname) errors.push(`${pathname}: canonical points to ${canonical}`);
  if (h1Count !== 1) errors.push(`${pathname}: ${h1Count} <h1> elements (expected 1)`);
}

for (const path of sitemapPaths) {
  if (!known.has(path)) errors.push(`sitemap: ${path} does not exist in dist/`);
}

console.log(`Checked ${pages.length} pages, ${sitemapPaths.size} in the sitemap.`);
for (const warning of warnings) console.warn(`warning: ${warning}`);
for (const error of errors) console.error(`ERROR: ${error}`);
if (errors.length > 0) {
  console.error(`${errors.length} error(s).`);
  process.exit(1);
}
console.log("All checks passed.");
