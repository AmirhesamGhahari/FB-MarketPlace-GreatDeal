// Titles, descriptions, headings and the model FAQ of every page type, read from web/seo_templates.yaml (the owner edits that
// file). A template is plain text with {placeholders}; a list of options is tried from the top, and an option is skipped when
// it needs a number the page does not have or when it is too long.
import YAML from "yaml";
import raw from "../../seo_templates.yaml?raw";
import type { CategoryProductCard, Deal, ProductSummary, SeriesPoint } from "./api";
import { formatDateTime, money } from "./format";
import { trendClause } from "./text";

type Values = Record<string, string | number | null | undefined>;
type Template = { title: string[]; description: string[]; h1: string };
type Faq = { q: string; a: string };

const file = YAML.parse(raw) as {
  global: { site_name: string; tagline: string; owner_name: string; contact_email: string; max_title_length: number; max_description_length: number };
  pages: Record<string, Template> & { model_faq: Faq[] };
};

export const SEO_GLOBAL = file.global;
// Where the numbers are from. Always Canada today; the multi-city phase passes the chosen city here (api_front_end.md, Phase 10).
export const DEFAULT_PLACE = "Canada";

export type PageKey = Exclude<keyof typeof file.pages, "model_faq">;

// Fills the {placeholders}; null when one has no value (so the caller can try the next option).
function fill(template: string, values: Values): string | null {
  let missing = false;
  const text = template.replace(/\{(\w+)\}/g, (_, key: string) => {
    const value = values[key];
    if (value === null || value === undefined || value === "") {
      missing = true;
      return "";
    }
    return String(value);
  });
  // A value that ends with a full stop (a date such as "12:14 p.m.") followed by the template's own full stop would print "..".
  return missing ? null : text.replace(/\.\.(?!\.)/g, ".");
}

const base = (): Values => ({
  site: SEO_GLOBAL.site_name,
  place: DEFAULT_PLACE,
  owner_name: SEO_GLOBAL.owner_name,
  contact_email: SEO_GLOBAL.contact_email,
});

// The first option that has all its numbers and fits `limit`; failing that the shortest one (with a build warning).
function choose(key: string, field: string, options: string[], values: Values, limit: number): string {
  const filled = options.map((option) => fill(option, values)).filter((text) => text !== null);
  if (filled.length === 0) throw new Error(`seo_templates.yaml: no ${field} option of "${key}" can be filled in (${JSON.stringify(values)})`);
  const fitting = filled.find((text) => text.length <= limit);
  if (fitting) return fitting;
  const shortest = filled.reduce((best, text) => (text.length < best.length ? text : best));
  console.warn(`[seo] ${key} ${field} is ${shortest.length} characters (limit ${limit}): ${shortest}`);
  return shortest;
}

// The title (without the site-name suffix, which Base.astro adds when it fits), description and H1 of a page.
export function pageMeta(key: PageKey, values: Values = {}) {
  const all = { ...base(), ...values };
  const template = file.pages[key] as Template;
  const h1 = fill(template.h1, all);
  if (h1 === null) throw new Error(`seo_templates.yaml: the h1 of "${key}" needs a value that is missing`);
  return {
    title: choose(key, "title", template.title, all, SEO_GLOBAL.max_title_length),
    description: choose(key, "description", template.description, all, SEO_GLOBAL.max_description_length),
    h1,
  };
}

// " | Tech Deal Radar" is added only when the whole title still fits (or the title already contains the name).
export function fullTitle(title: string): string {
  const suffix = ` | ${SEO_GLOBAL.site_name}`;
  return title.includes(SEO_GLOBAL.site_name) || title.length + suffix.length > SEO_GLOBAL.max_title_length ? title : `${title}${suffix}`;
}

const short = (value: number | null) => (value === null ? null : money(value));
const num = (value: number | null) => (value === null ? null : value.toLocaleString("en-CA"));

// Values of a model page. Give what the page has; the rest stays missing, so options that need it are skipped.
export function modelValues(product: ProductSummary, extra: { categoryName?: string; series?: SeriesPoint[]; deals?: Deal[]; dataAsOf?: string } = {}): Values {
  const best = extra.deals?.[0];
  const gap = best && best.price_diff_30d !== null && best.price_diff_30d < 0 ? -best.price_diff_30d : null;
  return {
    model: product.display_name,
    category: extra.categoryName,
    avg30: short(product.avg_price_30d),
    avg7: short(product.avg_price_7d),
    cutoff25: short(product.cutoff_price_cheapest_25pct_30d),
    listings30: num(product.listings_30d),
    listings7: num(product.listings_7d),
    trend_sentence: extra.series ? trendClause(extra.series) : null,
    best_price: best ? money(best.price) : null,
    best_gap: gap === null ? null : money(gap),
    best_gap_pct: gap !== null && best?.avg_price_30d ? Math.round((gap / best.avg_price_30d) * 100) : null,
    n_deals: extra.deals && extra.deals.length > 0 ? extra.deals.length : null,
    updated: extra.dataAsOf ? formatDateTime(extra.dataAsOf) : null,
  };
}

// Values of a category page or section page: its name, how many models have data, their listings and the range of their
// 30-day averages.
export function categoryValues(name: string, cards: CategoryProductCard[]): Values {
  const withData = cards.filter((card) => card.avg_price_30d !== null);
  const averages = withData.map((card) => card.avg_price_30d!);
  return {
    category: name,
    n_models: withData.length,
    listings30: num(withData.reduce((sum, card) => sum + (card.listings_30d ?? 0), 0)),
    avg_low: averages.length > 0 ? short(Math.min(...averages)) : null,
    avg_high: averages.length > 0 ? short(Math.max(...averages)) : null,
  };
}

// The visible FAQ of a model page (questions whose answer lacks a number are left out).
export function modelFaq(values: Values): Faq[] {
  const all = { ...base(), ...values };
  return file.pages.model_faq.flatMap((item) => {
    const q = fill(item.q, all);
    const a = fill(item.a, all);
    return q !== null && a !== null ? [{ q, a }] : [];
  });
}
