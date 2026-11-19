// Turns numbers into plain sentences (neutral and factual, no buying advice). Every helper returns null when a number it
// needs is missing, so the page simply leaves that sentence out instead of printing "null".
import type { ProductSummary } from "./api";
import { money } from "./format";

const plural = (n: number, one: string, many: string) => `${n.toLocaleString("en-CA")} ${n === 1 ? one : many}`;

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
