// The list of categories and products, fetched once per build and shared by every page (menus, hubs, sitemap, search).
// A module runs once and its variables stay alive for the whole build, so the first call fetches and the rest reuse it.
import { getCategories, getCategoryProducts, type CategoryProductCard } from "./api";

export type CatalogCategory = {
  category_key: string;
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
      return { category_key: category.category_key, category_name: category.category_name, products };
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
