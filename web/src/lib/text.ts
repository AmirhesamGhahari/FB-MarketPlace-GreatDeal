// Turns numbers into plain sentences (neutral and factual, no buying advice). Every helper returns null when a number it
// needs is missing, so the page simply leaves that sentence out instead of printing "null".
import type { Deal, ProductSummary, SeriesPoint } from "./api";
import { formatShortDate, money } from "./format";

export const plural = (n: number, one: string, many: string) => `${n.toLocaleString("en-CA")} ${n === 1 ? one : many}`;

// How far `value` is above (+) or below (-) `base`, in percent; null when either is unknown or base is 0.
export function percentDiff(value: number | null, base: number | null): number | null {
  if (value === null || base === null || base === 0) return null;
  return ((value - base) / base) * 100;
}

export function listingsSentence(name: string, listings30d: number | null, listings7d: number | null): string | null {
  if (listings30d === null) return null;
  const seven = listings7d === null ? "" : ` and ${plural(listings7d, "listing", "listings")} in the last 7 days`;
  return `${name} has ${plural(listings30d, "listing", "listings")} in the last 30 days${seven}.`;
}

export function averageSentence(avg30d: number | null): string | null {
  return avg30d === null ? null : `The 30-day average asking price is ${money(avg30d)}.`;
}

export function trendSentence(avg7d: number | null, avg30d: number | null): string | null {
  const diff = percentDiff(avg7d, avg30d);
  if (diff === null) return null;
  const pct = Math.round(Math.abs(diff));
  if (pct === 0) return `The 7-day average (${money(avg7d)}) is about the same as the 30-day average.`;
  return `The 7-day average (${money(avg7d)}) is ${pct}% ${diff < 0 ? "below" : "above"} the 30-day average.`;
}

export function cutoffSentence(cutoff30d: number | null): string | null {
  return cutoff30d === null ? null : `A quarter of the listings in the last 30 days are asking ${money(cutoff30d)} or less.`;
}

// The paragraph for the top of a product page.
export function productSummary(p: ProductSummary): string {
  return [
    listingsSentence(p.display_name, p.listings_30d, p.listings_7d),
    averageSentence(p.avg_price_30d),
    trendSentence(p.avg_price_7d, p.avg_price_30d),
    cutoffSentence(p.cutoff_price_cheapest_25pct_30d),
  ]
    .filter((sentence) => sentence !== null)
    .join(" ");
}

// "The 7-day average asking price went down from $1,150 to $1,088 over the last 30 days (-5%)."
function changeSentence(what: string, from: number | null, to: number | null, days: number): string | null {
  const diff = percentDiff(to, from);
  if (diff === null || from === null || to === null) return null;
  const pct = Math.round(Math.abs(diff));
  if (pct === 0) return `${what} stayed at about ${money(to)} over the last ${days} days.`;
  return `${what} went ${diff < 0 ? "down" : "up"} from ${money(from)} to ${money(to)} over the last ${days} days (${diff < 0 ? "-" : "+"}${pct}%).`;
}

// Four short facts for the top of the market-insights page, from the last 30 days of the series. Missing numbers drop a point.
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
      ? `The busiest day had ${plural(busiest.listings_1d!, "listing", "listings")} (${formatShortDate(busiest.stat_date)}) and the quietest had ${plural(quietest.listings_1d!, "listing", "listings")} (${formatShortDate(quietest.stat_date)}).`
      : null;

  return [
    changeSentence("The 7-day average asking price", first.avg_price_7d, last.avg_price_7d, window.length),
    changeSentence("The price that the cheapest 25% of listings fall under", first.cutoff_price_cheapest_25pct_30d, last.cutoff_price_cheapest_25pct_30d, window.length),
    activity,
    changeSentence("The 7-day average of high-scoring listings (deal score 8 or more)", first.deal8_avg_price_7d, last.deal8_avg_price_7d, window.length),
  ].filter((point) => point !== null);
}

// Sentences for the top of the top-deals page, from the deals the API ranked (cheapest first). Missing numbers drop a sentence.
export function dealsSentences(deals: Deal[]): string[] {
  const best = deals[0];
  if (!best) return [];
  const prices = deals.map((deal) => deal.price);
  const below =
    best.price_diff_30d !== null && best.price_diff_30d < 0 && best.avg_price_30d !== null
      ? `The best deal right now is ${money(best.price)}, ${money(-best.price_diff_30d)} below the 30-day average of ${money(best.avg_price_30d)}.`
      : `The best deal right now is ${money(best.price)}.`;
  const range =
    deals.length > 1
      ? `The ${deals.length} deals range from ${money(Math.min(...prices))} to ${money(Math.max(...prices))}.`
      : null;
  const cutoff = best.cutoff_price_cheapest_25pct_30d;
  const underCutoff =
    cutoff !== null && deals.every((deal) => deal.price < cutoff)
      ? `All of them are priced below ${money(cutoff)}, the price that the cheapest 25% of listings fall under.`
      : null;
  return [below, range, underCutoff].filter((sentence) => sentence !== null);
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

// Text for /market-insights/{category}/: how the models of one category moved over the last 30 days.
export function insightsCategorySentences(categoryName: string, items: Trend[]): string[] {
  if (items.length === 0) return [];
  if (items.length === 1) {
    return [`The 7-day average asking price of the ${items[0].name} changed by ${formatPct(items[0].pct)} over the last 30 days.`];
  }
  const byMove = [...items].sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct));
  const pcts = items.map((item) => item.pct);
  return [
    `Across the ${items.length} ${categoryName} models, the 7-day average asking price changed by ${formatPct(Math.min(...pcts))} to ${formatPct(Math.max(...pcts))} over the last 30 days.`,
    `The ${byMove[0].name} moved the most (${formatPct(byMove[0].pct)}) and the ${byMove[byMove.length - 1].name} the least (${formatPct(byMove[byMove.length - 1].pct)}).`,
  ];
}

// Text for /market-insights/: all categories together.
export function insightsRootSentences(categoryCount: number, items: Trend[]): string[] {
  if (items.length === 0) return [];
  const biggest = [...items].sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct))[0];
  return [
    `Price trends for ${plural(items.length, "used model", "used models")} in ${plural(categoryCount, "category", "categories")}.`,
    `Over the last 30 days the 7-day average asking price of the ${biggest.name} moved the most (${formatPct(biggest.pct)}).`,
  ];
}

type BestDeal = { name: string; deal: Deal };

// The deal with the biggest gap below its own 30-day average.
function biggestGap(items: BestDeal[]): BestDeal | null {
  const withGap = items.filter((item) => item.deal.price_diff_30d !== null && item.deal.price_diff_30d < 0);
  if (withGap.length === 0) return null;
  return withGap.reduce((best, item) => (item.deal.price_diff_30d! < best.deal.price_diff_30d! ? item : best));
}

// Text for /top-deals/{category}/ and /top-deals/: the best deal of each model is passed in. `subject` names what the deals
// are on, for example "2 iPhone models" or "4 models across 2 categories".
export function dealsHubSentences(subject: string, items: BestDeal[]): string[] {
  if (items.length === 0) return [];
  const best = biggestGap(items);
  return [
    `There are deals right now on ${subject}.`,
    best
      ? `The biggest gap below the average is on the ${best.name}: ${money(best.deal.price)}, ${money(-best.deal.price_diff_30d!)} below its 30-day average of ${money(best.deal.avg_price_30d)}.`
      : null,
  ].filter((sentence) => sentence !== null);
}
