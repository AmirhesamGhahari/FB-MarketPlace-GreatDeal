// API client used at BUILD time (Astro page frontmatter). The shapes below mirror the Pydantic schemas in
// api/src/fb_marketplace_api/schemas.py and the contract in api_contract.md.

// At build time (Node) the API is called by its full address; set API_BASE_URL (for example in web/.env) to point the build
// at another API. In the browser the page and the API share one address (CloudFront sends /api/* to the API), so the
// browser uses the relative path /api/v1: no cross-site request, and it keeps working when the site gets its own
// domain. `npm run dev` has no CloudFront in front, so there the browser uses /_api/v1, which the dev server forwards
// to the live API (see the proxy in astro.config.mjs).
const API_BASE =
  typeof window === "undefined"
    ? (import.meta.env.API_BASE_URL ?? "https://d2sru9uf6gw4cs.cloudfront.net/api/v1")
    : import.meta.env.DEV
      ? "/_api/v1"
      : "/api/v1";

// `T | null` means the API sends null when there is not enough data; the page must handle it.
export type Envelope<T> = { data_as_of: string; data: T };

export type Category = {
  category_key: string;
  category_name: string;
  brand: string;
  product_count: number;
};

export type CategoryProductCard = {
  slug: string;
  display_name: string;
  listings_30d: number | null;
  avg_price_30d: number | null;
  avg_price_7d: number | null;
  cutoff_price_cheapest_25pct_30d: number | null;
};

export type CategoryProducts = {
  category_key: string;
  category_name: string;
  products: CategoryProductCard[];
};

// One top deal of a product (see GET /v1/deals/{category_key}/top). Titles and cities come from free text, so they can be null.
export type Deal = {
  deal_rank: number;
  fb_listing_id: string;
  title: string | null;
  price: number;
  listing_url: string | null;
  location_city: string | null;
  listed_at: string;
  condition: string | null;
  avg_price_30d: number | null;
  price_diff_30d: number | null;
  cutoff_price_cheapest_25pct_30d: number | null;
};

export type ProductDeals = {
  slug: string;
  display_name: string;
  category_key: string;
  deals: Deal[];
};

export type LowestDeal = { listing_id: string; url: string | null; price: number };

export type ProductSummary = {
  slug: string;
  display_name: string;
  category_key: string;
  as_of_date: string;
  listings_30d: number | null;
  avg_price_30d: number | null;
  listings_7d: number | null;
  avg_price_7d: number | null;
  deal8_listings_30d: number | null;
  deal8_avg_price_30d: number | null;
  deal8_listings_7d: number | null;
  deal8_avg_price_7d: number | null;
  cutoff_price_cheapest_25pct_30d: number | null;
  cutoff_price_cheapest_25pct_7d: number | null;
  lowest_5_deals_30d: LowestDeal[] | null;
  lowest_5_deals_7d: LowestDeal[] | null;
  deal8_lowest_5_deals_30d: LowestDeal[] | null;
  deal8_lowest_5_deals_7d: LowestDeal[] | null;
};

// One day of chart data (GET /v1/products/{slug}/series). Early days can have null averages.
export type SeriesPoint = {
  stat_date: string;
  listings_1d: number | null;
  avg_price_1d: number | null;
  avg_price_3d: number | null;
  avg_price_7d: number | null;
  avg_price_30d: number | null;
  deal8_listings_1d: number | null;
  deal8_avg_price_7d: number | null;
  deal8_avg_price_30d: number | null;
  lowest_3_deals_7d: LowestDeal[] | null;
  cutoff_price_cheapest_25pct_30d: number | null;
  cutoff_price_cheapest_25pct_7d: number | null;
  // The average price of the up to 5 cheapest listings posted that day. Optional: the live API only sends it after the
  // 2026-11-24 update (api_contract.md 2.4).
  lowest_5_avg_1d?: number | null;
};

// Up to 60 days, oldest first; the last element is today (partial).
export type ProductSeries = { slug: string; series: SeriesPoint[] };

// One row of the listings table (GET /v1/products/{slug}/listings/all). Free-text fields can be null.
export type ListingRow = {
  fb_listing_id: string;
  listing_url: string | null;
  title: string | null;
  price: number;
  condition: string | null;
  storage_gb: number | null;
  color: string | null;
  location_city: string | null;
  listed_at: string;
  days_ago: number;
  avg_price_30d: number | null;
  avg_price_7d: number | null;
  price_diff_30d: number | null;
  price_diff_7d: number | null;
};

// The first request after a quiet period can wake the paused Aurora cluster (the API itself waits up to ~23 s and may
// answer 503 database_resuming). A build must survive that, so it waits long and retries.
const MAX_ATTEMPTS = 6;
const TIMEOUT_MS = 45_000;

// The API is deliberately small: API Gateway lets through about 2 requests a second (a short burst of 5), and the database
// is tiny. A build with many products needs hundreds of requests, so at most 3 are in flight at a time. Answers CloudFront has
// already cached never reach the API and come back fast, so requests start without a gap; after the first "429 too many
// requests" the build spaces its requests out (SLOW_GAP_MS) for the rest of the run.
const MAX_IN_FLIGHT = 3;
const SLOW_GAP_MS = 600;
let minGap = 0;
let inFlight = 0;
let lastStart = 0;
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function acquireSlot() {
  // The check and the increment below happen with no await in between, so two callers can never take the same slot.
  while (inFlight >= MAX_IN_FLIGHT || Date.now() - lastStart < minGap) await sleep(50);
  inFlight++;
  lastStart = Date.now();
}

async function get<T>(path: string): Promise<Envelope<T>> {
  const url = `${API_BASE}${path}`;
  for (let attempt = 1; ; attempt++) {
    let pauseMs = 0;
    await acquireSlot();
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_MS) });
      if (res.ok) return (await res.json()) as Envelope<T>;
      if (res.status === 429) {
        // Too many requests: wait before trying again (the API's own retry hint if it sends one).
        minGap = SLOW_GAP_MS;
        pauseMs = Number(res.headers.get("retry-after")) * 1000 || 2000 * attempt;
        console.warn(`[api] ${url} answered 429, waiting ${pauseMs} ms (attempt ${attempt}/${MAX_ATTEMPTS})`);
      } else if (res.status === 503) {
        // No pause: the API has already waited for the database before it answers 503.
        console.warn(`[api] ${url} answered 503 (attempt ${attempt}/${MAX_ATTEMPTS})`);
      } else {
        throw new Error(`API ${res.status} for ${url}`); // 404/422: retrying will not help
      }
    } catch (err) {
      if (err instanceof Error && err.message.startsWith("API ")) throw err;
      console.warn(`[api] ${url} failed: ${err} (attempt ${attempt}/${MAX_ATTEMPTS})`);
      pauseMs = 1000;
    } finally {
      inFlight--;
    }
    if (attempt >= MAX_ATTEMPTS) throw new Error(`API unreachable after ${MAX_ATTEMPTS} attempts: ${url}`);
    if (pauseMs > 0) await sleep(pauseMs);
  }
}

export const getCategories = () => get<Category[]>("/categories");
export const getCategoryProducts = (categoryKey: string) => get<CategoryProducts>(`/categories/${categoryKey}/products`);
export const getProduct = (slug: string) => get<ProductSummary>(`/products/${slug}`);
export const getTopDeals = (categoryKey: string) => get<ProductDeals[]>(`/deals/${categoryKey}/top`);
export const getSeries = (slug: string) => get<ProductSeries>(`/products/${slug}/series`);
export const getListingsAll = (slug: string) => get<ListingRow[]>(`/products/${slug}/listings/all`);
