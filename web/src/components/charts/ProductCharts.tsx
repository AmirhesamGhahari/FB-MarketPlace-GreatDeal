// All the charts of one product with one period filter above them (the insights page), and the daily numbers table below. The
// data is baked into the page at build time; picking a period only changes which of the 60 days are drawn, so no request is made.
import { useState } from "react";
import type { SeriesPoint } from "../../lib/api";
import { formatShortDate, moneyShort } from "../../lib/format";
import DailyTable from "./DailyTable";
import DealsPanel from "./DealsPanel";
import StackedPanel from "./StackedPanel";
import { SERIES_COLORS } from "./theme";

const PERIODS = [10, 20, 30, 60] as const;
const [blue, orange, aqua] = SERIES_COLORS;

// Total listings of the 30 days up to each day. It needs 30 days of history, so the first 29 days of the series have none.
function rollingTotals(series: SeriesPoint[]): (number | null)[] {
  return series.map((_, index) => {
    if (index < 29) return null;
    const window = series.slice(index - 29, index + 1);
    return window.some((day) => day.listings_1d === null) ? null : window.reduce((sum, day) => sum + (day.listings_1d ?? 0), 0);
  });
}

type Day = SeriesPoint & { listings_30d_total: number | null };
const lastNumber = (rows: Day[], pick: (day: Day) => number | null | undefined) => {
  for (let i = rows.length - 1; i >= 0; i--) {
    const value = pick(rows[i]);
    if (typeof value === "number") return value;
  }
  return null;
};
const firstNumber = (rows: Day[], pick: (day: Day) => number | null | undefined) => lastNumber([...rows].reverse(), pick);

export default function ProductCharts({ series }: { series: SeriesPoint[] }) {
  const [days, setDays] = useState<number>(30);
  const totals = rollingTotals(series);
  const start = Math.max(0, series.length - days);
  // The rows the charts draw: the chosen days, each with its rolling 30-day total.
  const rows: Day[] = series.slice(start).map((day, index) => ({ ...day, listings_30d_total: totals[start + index] }));

  // The key numbers shown above the charts.
  const firstPrice = firstNumber(rows, (day) => day.avg_price_1d);
  const lastPrice = lastNumber(rows, (day) => day.avg_price_1d);
  const change = firstPrice && lastPrice ? ((lastPrice - firstPrice) / firstPrice) * 100 : null;
  const fullDays = rows.slice(0, -1).filter((day) => typeof day.listings_1d === "number");
  const perDay = fullDays.length === 0 ? null : fullDays.reduce((sum, day) => sum + (day.listings_1d ?? 0), 0) / fullDays.length;
  const cheapestPoints = rows.flatMap((day) => (day.lowest_3_deals_7d ?? []).map((deal) => ({ price: deal.price, day: day.stat_date })));
  const lowest = cheapestPoints.length === 0 ? null : cheapestPoints.reduce((best, point) => (point.price < best.price ? point : best));

  return (
    <div>
      <div role="group" aria-label="Period" className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-sm text-slate-500">Show the last</span>
        {PERIODS.map((period) => (
          <button
            key={period}
            type="button"
            aria-pressed={days === period}
            onClick={() => setDays(period)}
            className={`rounded-full px-3 py-1 text-sm font-medium ${
              days === period ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            {period} days
          </button>
        ))}
      </div>
      <p className="mt-2 text-sm text-slate-500">The newest day is still in progress ("today so far").</p>

      <div className="mt-6 space-y-6">
        <StackedPanel
          title="Average asking price and listings per day"
          subtitle="The line is the average asking price of each day; the columns are the number of listings posted that day."
          syncId="price-and-listings"
          headline={[
            { label: "Latest daily average", value: lastPrice === null ? "n/a" : moneyShort(lastPrice) },
            {
              label: `Change over ${days} days`,
              value: change === null ? "n/a" : `${change > 0 ? "+" : ""}${change.toFixed(1)}%`,
              tone: change === null ? undefined : change < 0 ? "good" : change > 0 ? "bad" : undefined,
            },
            { label: "Listings per day", value: perDay === null ? "n/a" : perDay.toFixed(0), hint: "average of full days" },
          ]}
          rows={rows}
          lines={[{ key: "avg_price_1d", label: "Average asking price", color: blue }]}
          bar={{ key: "listings_1d", label: "Listings per day", color: orange }}
        />
        <StackedPanel
          title="30-day average, cheapest 25% and listings"
          subtitle="Both lines look back 30 days. The columns are the total number of listings in the last 30 days (shown once 30 days of history exist)."
          syncId="averages-and-total"
          headline={[
            { label: "30-day average now", value: lastNumber(rows, (day) => day.avg_price_30d) === null ? "n/a" : moneyShort(lastNumber(rows, (day) => day.avg_price_30d)) },
            { label: "Cheapest 25% under", value: lastNumber(rows, (day) => day.cutoff_price_cheapest_25pct_30d) === null ? "n/a" : moneyShort(lastNumber(rows, (day) => day.cutoff_price_cheapest_25pct_30d)) },
            { label: "Listings, last 30 days", value: lastNumber(rows, (day) => day.listings_30d_total) === null ? "n/a" : lastNumber(rows, (day) => day.listings_30d_total)!.toLocaleString("en-CA") },
          ]}
          rows={rows}
          lines={[
            { key: "avg_price_30d", label: "30-day average", color: blue },
            { key: "cutoff_price_cheapest_25pct_30d", label: "Cheapest 25% (30 days)", color: orange },
          ]}
          bar={{ key: "listings_30d_total", label: "Listings in the last 30 days", color: aqua }}
        />
        <DealsPanel
          title="Cheapest listings by day"
          subtitle="Up to three cheapest listings of the previous 7 days at each date. Hover a dot for details, click or tap it to open the listing on Facebook."
          rows={rows}
          headline={[
            { label: "Lowest listing in this period", value: lowest ? moneyShort(lowest.price) : "n/a", hint: lowest ? formatShortDate(lowest.day) : undefined },
            { label: "Dots shown", value: String(cheapestPoints.length), hint: "up to 3 per day" },
          ]}
        />
      </div>

      <section className="mt-10">
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">Daily numbers</h2>
        <p className="mt-1 text-sm text-slate-500">Every day of the chosen period, newest first.</p>
        <div className="mt-4">
          <DailyTable rows={rows} />
        </div>
      </section>
    </div>
  );
}
