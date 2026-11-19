// All the charts of one product with one period filter above them (the insights page). The data is baked into the page at
// build time; picking a period only changes which of the 60 days are drawn, so no request is made.
import { useState } from "react";
import type { SeriesPoint } from "../../lib/api";
import ColumnPanel from "./ColumnPanel";
import DealsPanel from "./DealsPanel";
import LinePanel from "./LinePanel";
import { SERIES_COLORS } from "./theme";

const PERIODS = [10, 20, 30, 60] as const;
const [blue, orange, aqua] = SERIES_COLORS;

export default function ProductCharts({ series }: { series: SeriesPoint[] }) {
  const [days, setDays] = useState<number>(30);
  const rows = series.slice(-days);

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
        <LinePanel
          title="Average asking price per day"
          rows={rows}
          series={[{ key: "avg_price_1d", label: "Daily average", color: blue }]}
        />
        <ColumnPanel title="Listings per day" rows={rows} dataKey="listings_1d" label="Listings" />
        <LinePanel
          title="Average price over 3, 7 and 30 days"
          subtitle="Longer averages move more slowly, so they show the trend."
          rows={rows}
          series={[
            { key: "avg_price_3d", label: "3-day average", color: blue },
            { key: "avg_price_7d", label: "7-day average", color: orange },
            { key: "avg_price_30d", label: "30-day average", color: aqua },
          ]}
        />
        <LinePanel
          title="Average price of high-scoring listings (deal score 8+)"
          rows={rows}
          series={[
            { key: "deal8_avg_price_7d", label: "7-day average", color: blue },
            { key: "deal8_avg_price_30d", label: "30-day average", color: orange },
          ]}
        />
        <ColumnPanel
          title="High-scoring listings per day (deal score 8+)"
          rows={rows}
          dataKey="deal8_listings_1d"
          label="Listings"
        />
        <DealsPanel
          title="Cheapest listings by day"
          subtitle="Up to three cheapest listings of the previous 7 days at each date. Click a dot to open the listing on Facebook."
          rows={rows}
        />
        <LinePanel
          title="Price of the cheapest 25% of listings"
          subtitle="A quarter of the listings were asking this much or less."
          rows={rows}
          series={[
            { key: "cutoff_price_cheapest_25pct_30d", label: "Over 30 days", color: blue },
            { key: "cutoff_price_cheapest_25pct_7d", label: "Over 7 days", color: orange },
          ]}
        />
      </div>
    </div>
  );
}
