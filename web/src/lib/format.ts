// Display helpers shared by all pages.

// The API sends null when there is not enough data; show text instead of crashing or printing "null".
export function money(value: number | null): string {
  return value === null ? "Not enough data" : `$${Math.round(value).toLocaleString("en-CA")} CAD`;
}

// Same without the currency suffix, for page titles where every character counts (Google cuts titles near 60).
export function moneyShort(value: number | null): string {
  return value === null ? "n/a" : `$${Math.round(value).toLocaleString("en-CA")}`;
}

// "2026-11-09T16:13:31.684588-05:00" -> "November 9, 2026, 4:13 p.m." (Toronto time, as in the API).
export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "long",
    timeStyle: "short",
    timeZone: "America/Toronto",
  }).format(new Date(iso));
}

// A price minus the average: -235.2 -> "-$235", 80 -> "+$80". Negative means cheaper than average.
export function formatPriceDiff(diff: number): string {
  const rounded = Math.round(diff);
  const sign = rounded < 0 ? "-" : rounded > 0 ? "+" : "";
  return `${sign}$${Math.abs(rounded).toLocaleString("en-CA")}`;
}

// "2026-10-27T02:10:23-04:00" -> "Oct 27, 2026" (Toronto calendar day, as in the API).
export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { dateStyle: "medium", timeZone: "America/Toronto" }).format(new Date(iso));
}
