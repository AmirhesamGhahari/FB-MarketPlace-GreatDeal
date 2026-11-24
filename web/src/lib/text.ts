// Turns numbers into plain sentences (neutral and factual, no buying advice). Every helper returns null when a number it
// needs is missing, so the page simply leaves that sentence out instead of printing "null".
import type { Deal, ProductSummary, SeriesPoint } from "./api";
import { formatShortDate, money } from "./format";
import { SITE_NAME } from "./site";

// The first title option that fits (the layout adds " | Site name"; Google shows about 60 characters, and check-site warns
// above 70 in total). Long model names such as "PlayStation 5 Slim Digital Edition" fall back to a shorter wording.
export function fitTitle(options: string[]): string {
  const limit = 70 - ` | ${SITE_NAME}`.length;
  return options.find((title) => title.length <= limit) ?? options[options.length - 1];
}

// The average price of a few listings (for example the 5 cheapest), or null without any.
export function averagePrice(listings: { price: number }[] | null | undefined): number | null {
  return listings && listings.length > 0 ? listings.reduce((sum, listing) => sum + listing.price, 0) / listings.length : null;
}

// How many listings about a quarter of `total` is (the cheapest-25% price has a quarter of the listings under it).
export const quarterOf = (total: number | null) => (total === null ? null : Math.round(total / 4));

export const plural = (n: number, one: string, many: string) => `${n.toLocaleString("en-CA")} ${n === 1 ? one : many}`;

// How far `value` is above (+) or below (-) `base`, in percent; null when either is unknown or base is 0.
export function percentDiff(value: number | null, base: number | null): number | null {
  if (value === null || base === null || base === 0) return null;
  return ((value - base) / base) * 100;
}

export function listingsSentence(name: string, listings30d: number | null, listings7d: number | null): string | null {
  if (listings30d === null) return null;
  const seven = listings7d === null ? "" : ` (${listings7d.toLocaleString("en-CA")} in the last 7 days)`;
  const plenty = listings30d >= 50 ? ", so there is plenty to compare" : "";
  return `${name} has ${plural(listings30d, "listing", "listings")} in the last 30 days${seven}${plenty}.`;
}

export function averageSentence(avg30d: number | null): string | null {
  return avg30d === null ? null : `The 30-day average asking price is ${money(avg30d)}.`;
}

export function trendSentence(avg7d: number | null, avg30d: number | null): string | null {
  const diff = percentDiff(avg7d, avg30d);
  if (diff === null) return null;
  const pct = Math.round(Math.abs(diff));
  if (pct === 0) return `The 7-day average (${money(avg7d)}) is about the same, so prices are holding steady.`;
  return `The 7-day average (${money(avg7d)}) is ${pct}% ${diff < 0 ? "below" : "above"} it, so asking prices are drifting ${diff < 0 ? "down" : "up"}.`;
}

export function cutoffSentence(cutoff30d: number | null): string | null {
  return cutoff30d === null
    ? null
    : `A quarter of the listings ask ${money(cutoff30d)} or less: a price near or under that is cheaper than most.`;
}

// The paragraph for the top of a product page.
export function productSummary(p: ProductSummary): string {
  return [
    listingsSentence(p.display_name, p.listings_30d, p.listings_7d),
    averageSentence(p.avg_price_30d),
    trendSentence(p.avg_price_7d, p.avg_price_30d),
    cutoffSentence(p.cutoff_price_cheapest_25pct_30d),
    "Scroll down for the price trend and the cheapest deals right now.",
  ]
    .filter((sentence) => sentence !== null)
    .join(" ");
}

// "went down from $1,150 to $1,088 (-5%)", or "stayed at about $1,088" when the move rounds to 0%; null without both numbers.
function moveClause(from: number | null, to: number | null): string | null {
  const diff = percentDiff(to, from);
  if (diff === null || from === null || to === null) return null;
  const pct = Math.round(Math.abs(diff));
  if (pct === 0) return `stayed at about ${money(to)}`;
  return `went ${diff < 0 ? "down" : "up"} from ${money(from)} to ${money(to)} (${diff < 0 ? "-" : "+"}${pct}%)`;
}

// Three short facts for the top of the market-insights page, from the last 30 days of the series. Missing numbers drop a point.
export function insightPoints(series: SeriesPoint[]): string[] {
  const window = series.slice(-30);
  const first = window[0];
  const last = window[window.length - 1];
  if (!first || !last) return [];

  // Today is only partly over, so it cannot be "the quietest day".
  const fullDays = window.slice(0, -1).filter((day) => day.listings_1d !== null);
  const busiest = fullDays.reduce<SeriesPoint | null>((best, day) => (!best || day.listings_1d! > best.listings_1d! ? day : best), null);
  const quietest = fullDays.reduce<SeriesPoint | null>((low, day) => (!low || day.listings_1d! < low.listings_1d! ? day : low), null);
  const activity =
    busiest && quietest
      ? `New listings appear every day, from ${plural(quietest.listings_1d!, "listing", "listings")} on the quietest day (${formatShortDate(quietest.stat_date)}) to ${busiest.listings_1d!.toLocaleString("en-CA")} on the busiest (${formatShortDate(busiest.stat_date)}). The daily chart shows when the cheap ones tend to arrive.`
      : null;

  const average = moveClause(first.avg_price_7d, last.avg_price_7d);
  const cutoff = moveClause(first.cutoff_price_cheapest_25pct_30d, last.cutoff_price_cheapest_25pct_30d);
  const days = window.length;
  return [
    average && `Over the last ${days} days the 7-day average asking price ${average}.`,
    cutoff &&
      `The "cheap" line, the price that the cheapest 25% of listings fall under, ${cutoff}. Anything asking less than that is cheaper than about three quarters of the market.`,
    activity,
  ].filter((point): point is string => typeof point === "string" && point !== "");
}

// Sentences for the top of the top-deals page, from the deals the API ranked (cheapest first). Missing numbers drop a sentence.
export function dealsSentences(deals: Deal[]): string[] {
  const best = deals[0];
  if (!best) return [];
  const prices = deals.map((deal) => deal.price);
  const gap = best.price_diff_30d !== null && best.price_diff_30d < 0 && best.avg_price_30d !== null ? -best.price_diff_30d : null;
  const below =
    gap !== null
      ? `Right now the best deal asks ${money(best.price)}, ${money(gap)} (${Math.round((gap / best.avg_price_30d!) * 100)}%) under the 30-day average of ${money(best.avg_price_30d)}.`
      : `Right now the best deal asks ${money(best.price)}.`;
  const range =
    deals.length > 1
      ? `The ${deals.length} listings below run from ${money(Math.min(...prices))} to ${money(Math.max(...prices))}${
          best.avg_price_30d !== null && Math.max(...prices) < best.avg_price_30d ? ", so even the last one on the list is under the average" : ""
        }.`
      : null;
  const cutoff = best.cutoff_price_cheapest_25pct_30d;
  const underCutoff =
    cutoff !== null && deals.every((deal) => deal.price < cutoff)
      ? `All of them are also under ${money(cutoff)}, the price that the cheapest 25% of listings fall under.`
      : null;
  const lead = "Use them to see what a good price looks like, and check back after each data refresh: new cheap listings can appear at any time.";
  return [below, range, underCutoff, lead].filter((sentence) => sentence !== null);
}

// How the 7-day average moved over the last 30 days of a series (null when a number is missing).
export function trend30(series: SeriesPoint[]): { pct: number; from: number; to: number } | null {
  const window = series.slice(-30);
  const from = window[0]?.avg_price_7d ?? null;
  const to = window[window.length - 1]?.avg_price_7d ?? null;
  const pct = percentDiff(to, from);
  return pct === null || from === null || to === null ? null : { pct, from, to };
}

// -5.2 -> "-5%", 3 -> "+3%", 0.2 -> "0%"
export const formatPct = (pct: number) => `${Math.round(pct) > 0 ? "+" : Math.round(pct) < 0 ? "-" : ""}${Math.abs(Math.round(pct))}%`;

type Trend = { name: string; pct: number };

// "fell on 9 models, rose on 5 and held steady on 3" for the 7-day average over the last 30 days (a move under 0.5% is steady).
function movesClause(items: Trend[], noun: string): string {
  const steady = (item: Trend) => Math.round(item.pct) === 0;
  const parts = [
    [items.filter((item) => item.pct < 0 && !steady(item)).length, "fell on"],
    [items.filter((item) => item.pct > 0 && !steady(item)).length, "rose on"],
    [items.filter(steady).length, "held steady on"],
  ]
    .filter(([n]) => n !== 0)
    .map(([n, verb]) => `${verb} ${plural(n as number, noun, `${noun}s`)}`);
  return parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : (parts[0] ?? "");
}

// Text for /market-insights/{category}/: how the models of one category moved over the last 30 days.
export function insightsCategorySentences(categoryName: string, items: Trend[]): string[] {
  if (items.length === 0) return [];
  const lead = "Open a model for its full price history, the listings that arrive each day and the cheapest deals right now.";
  if (items.length === 1) {
    return [`The 7-day average asking price of the ${items[0].name} changed by ${formatPct(items[0].pct)} over the last 30 days.`, lead];
  }
  return [
    `In the last 30 days the 7-day average asking price ${movesClause(items, `${categoryName} model`)}.`,
    "Falling prices show where buyers are getting the best chances, and rising ones show where waiting may cost more.",
    lead,
  ];
}

// Text for /market-insights/: all categories together.
export function insightsRootSentences(categoryCount: number, items: Trend[]): string[] {
  if (items.length === 0) return [];
  return [
    `Price trends for ${plural(items.length, "used model", "used models")} in ${plural(categoryCount, "category", "categories")}.`,
    `In the last 30 days the 7-day average asking price ${movesClause(items, "model")}.`,
    "Open a category to see which models are getting cheaper, then follow the cheapest listings to learn what a good price looks like and catch cheap deals as they appear.",
  ];
}

type BestDeal = { name: string; deal: Deal };

// How far below its model's 30-day average a deal is, in percent (null when there is no average).
const gapPercent = (deal: Deal) =>
  deal.price_diff_30d !== null && deal.avg_price_30d ? Math.round((-deal.price_diff_30d / deal.avg_price_30d) * 100) : null;

// Text for /top-deals/{category}/ and /top-deals/: the best deal of each model is passed in. `subject` names what the deals
// are on, for example "2 iPhone models" or "4 models across 2 categories".
export function dealsHubSentences(subject: string, items: BestDeal[]): string[] {
  if (items.length === 0) return [];
  const gaps = items.map((item) => gapPercent(item.deal)).filter((gap) => gap !== null).sort((a, b) => a - b);
  const median = gaps.length > 0 ? gaps[Math.floor(gaps.length / 2)] : null;
  const deep = gaps.filter((gap) => gap >= 25).length;
  return [
    `There are deals right now on ${subject}.`,
    median !== null && median > 0
      ? `The cheapest listing of each model typically sits ${median}% below its 30-day average${deep > 0 ? `, and ${plural(deep, "model has", "models have")} a listing at least 25% under` : ""}.`
      : null,
    "Cheap listings come and go fast, so the deals pages show the cheapest ones next to the average price: a quick way to learn what a good price is and to spot a bargain the moment it appears.",
  ].filter((sentence) => sentence !== null);
}
