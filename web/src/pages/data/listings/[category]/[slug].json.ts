// /data/listings/{category}/{slug}.json (the same folders as the page address): every recent listing of one model as a plain static file, written at build time from the API's
// /listings/all answer. The listings table in the browser loads this file (served by CloudFront and S3) instead of calling the API,
// so there is no Lambda cold start, no database wake-up and no shared API throttle on the visitor's path. The data is exactly as
// fresh as the pages, because both come from the same build.
//
// A model whose listings cannot be fetched gets no file (the table then falls back to the live API). That only warns, except in
// the build for launch (PUBLIC_SITE_LIVE=true), which stops so the site never goes live with missing files.
import type { APIRoute, GetStaticPaths } from "astro";
import { getProductListings, getProductPaths } from "../../../../lib/catalog";
import { SITE_LIVE } from "../../../../lib/site";

export const getStaticPaths = (async () => {
  const products = (await getProductPaths()).map(({ params }) => ({ category: params.category as string, slug: params.slug as string }));
  const loaded = await Promise.all(products.map(async (product) => ({ ...product, envelope: await getProductListings(product.slug) })));

  const missing = loaded.filter((item) => item.envelope === null).map((item) => `${item.category}/${item.slug}`);
  if (missing.length > 0) {
    const message = `${missing.length} of ${loaded.length} models have no listings file because the API's /listings/all failed: ${missing.slice(0, 5).join(", ")}${missing.length > 5 ? ", ..." : ""}`;
    if (SITE_LIVE) throw new Error(`${message}. The live build stops so the site does not launch with broken listings tables.`);
    console.warn(`[listings] ${message}. The tables will use the live API instead.`);
  }

  return loaded.flatMap((item) =>
    item.envelope ? [{ params: { category: item.category, slug: item.slug }, props: { envelope: item.envelope } }] : [],
  );
}) satisfies GetStaticPaths;

export const GET: APIRoute = ({ props }) =>
  new Response(JSON.stringify(props.envelope), { headers: { "content-type": "application/json; charset=utf-8" } });
