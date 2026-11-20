// The list of categories and products, fetched once per build and shared by every page (menus, hubs, sitemap, search).
// A module runs once and its variables stay alive for the whole build, so the first call fetches and the rest reuse it.
import { getCategories, getCategoryProducts, getProduct, getSeries, getTopDeals, type CategoryProductCard } from "./api";

// The API's category keys use underscores (apple_watch). URLs use hyphens (apple-watch), which search engines read as word
// separators, so `category_key` here is the URL form. Only the calls to the API convert back (toApiKey).
export const toUrlKey = (key: string) => key.replaceAll("_", "-");
export const toApiKey = (urlKey: string) => urlKey.replaceAll("-", "_");

// Names that read better in titles such as "Used Smart Ring Prices in Canada" than the database's own name.
const CATEGORY_NAME_OVERRIDES: Record<string, string> = { smart_rings: "Smart Ring" };

// Products with the most listings first (a fair way to choose which models to show when space is short).
export const byPopularity = (a: CategoryProductCard, b: CategoryProductCard) => (b.listings_30d ?? 0) - (a.listings_30d ?? 0);

export type CatalogCategory = {
  category_key: string; // URL form, see above
  category_name: string;
  products: CategoryProductCard[];
};

export type Catalog = {
  categories: CatalogCategory[];
  data_as_of: string;
};

let cached: Promise<Catalog> | undefined;

async function load(): Promise<Catalog> {  const { data: categories, data_as_of } = await getCategories();
  const loaded = await Promise.all(
    categories.map(async (category) => {
      const { products } = (await getCategoryProducts(category.category_key)).data;
      return {
        category_key: toUrlKey(category.category_key),
        category_name: CATEGORY_NAME_OVERRIDES[category.category_key] ?? category.category_name,
        products,
      };
    }),
  );
  return { categories: loaded, data_as_of };
}

// Storing the promise (not the result) means pages that ask at the same moment share one fetch.
export function getCatalog(): Promise<Catalog> {
  cached ??= load();
  return cached;
}

// A catalog product without data has null stats and no product page (the API answers 404 for it).
export const hasData = (product: CategoryProductCard) => product.avg_price_30d !== null;

// The top deals of a category, fetched once per category and build: every product page of the category needs them.
const dealsCache = new Map<string, ReturnType<typeof getTopDeals>>();
export function getCategoryDeals(categoryKey: string) {
  let deals = dealsCache.get(categoryKey);
  if (!deals) {
    deals = getTopDeals(toApiKey(categoryKey));
    dealsCache.set(categoryKey, deals);
  }
  return deals;
}

// Every product page of the site as getStaticPaths entries: /{category}/{slug}/ and its section pages share this list.
export async function getProductPaths() {
  const { categories } = await getCatalog();
  return categories.flatMap((category) =>
    category.products
      .filter(hasData)
      .map((product) => ({ params: { category: category.category_key, slug: product.slug } })),
  );
}

// The chart series of a product, fetched once per build: the overview, insights and category pages all use it.
const seriesCache = new Map<string, ReturnType<typeof getSeries>>();
export function getProductSeries(slug: string) {
  let series = seriesCache.get(slug);
  if (!series) {
    series = getSeries(slug);
    seriesCache.set(slug, series);
  }
  return series;
}

// The summary (headline numbers) of a product, fetched once per build and shared by its pages and the footer.
const summaryCache = new Map<string, ReturnType<typeof getProduct>>();
export function getProductSummary(slug: string) {
  let summary = summaryCache.get(slug);
  if (!summary) {
    summary = getProduct(slug);
    summaryCache.set(slug, summary);
  }
  return summary;
}

// When the price data was last updated: the OLDEST update time among all products, so every number shown is at least this
// fresh (the catalog's own timestamp only says when the product list was built).
export async function getPricesUpdatedAt(): Promise<string> {
  const catalog = await getCatalog();
  const slugs = catalog.categories.flatMap((category) => category.products.filter(hasData).map((product) => product.slug));
  const stamps = await Promise.all(slugs.map(async (slug) => (await getProductSummary(slug)).data_as_of));
  if (stamps.length === 0) return catalog.data_as_of;
  return stamps.reduce((oldest, stamp) => (new Date(stamp) < new Date(oldest) ? stamp : oldest));
}
