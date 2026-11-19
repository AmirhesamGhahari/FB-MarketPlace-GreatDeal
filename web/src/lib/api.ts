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
// answer 503 database_resuming). A build must survive that, so it waits long and retries. No pause between attempts:
// the API has already waited for the database before it answers 503.
const MAX_ATTEMPTS = 4;
const TIMEOUT_MS = 45_000;

async function get<T>(path: string): Promise<Envelope<T>> {
  const url = `${API_BASE}${path}`;
  for (let attempt = 1; ; attempt++) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_MS) });
      if (res.ok) return (await res.json()) as Envelope<T>;
      if (res.status !== 503) throw new Error(`API ${res.status} for ${url}`); // 404/422: retrying will not help
      console.warn(`[api] ${url} answered 503 (attempt ${attempt}/${MAX_ATTEMPTS})`);
    } catch (err) {
      if (err instanceof Error && err.message.startsWith("API ")) throw err;
      console.warn(`[api] ${url} failed: ${err} (attempt ${attempt}/${MAX_ATTEMPTS})`);
    }
    if (attempt >= MAX_ATTEMPTS) throw new Error(`API unreachable after ${MAX_ATTEMPTS} attempts: ${url}`);
  }
}

export const getCategories = () => get<Category[]>("/categories");
export const getCategoryProducts = (categoryKey: string) => get<CategoryProducts>(`/categories/${categoryKey}/products`);
export const getProduct = (slug: string) => get<ProductSummary>(`/products/${slug}`);
export const getTopDeals = (categoryKey: string) => get<ProductDeals[]>(`/deals/${categoryKey}/top`);
export const getSeries = (slug: string) => get<ProductSeries>(`/products/${slug}/series`);
export const getListingsAll = (slug: string) => get<ListingRow[]>(`/products/${slug}/listings/all`);
