// The day-by-day numbers as a table that follows the period chosen above the charts, newest day first, in pages of rows.
// It is real text in the page's HTML (the first page), so it also helps search engines.
import { useState } from "react";
import type { SeriesPoint } from "../../lib/api";
import { count, formatShortDate, money } from "../../lib/format";

const PAGE_SIZE = 15;

// The cheapest of the up to three lowest listings of that day.
const lowest = (row: SeriesPoint) => {
  const prices = (row.lowest_3_deals_7d ?? []).map((deal) => deal.price);
  return prices.length > 0 ? Math.min(...prices) : null;
};

const COLUMNS: { label: string; value: (row: SeriesPoint) => string }[] = [
  { label: "Day", value: (row) => formatShortDate(row.stat_date) },
  { label: "Daily average", value: (row) => money(row.avg_price_1d) },
  { label: "7-day average", value: (row) => money(row.avg_price_7d) },
  { label: "30-day average", value: (row) => money(row.avg_price_30d) },
  { label: "Cheapest 25% under", value: (row) => money(row.cutoff_price_cheapest_25pct_30d) },
  { label: "Lowest listing", value: (row) => money(lowest(row)) },
  { label: "Listings", value: (row) => count(row.listings_1d) },
  { label: "High-scoring listings", value: (row) => count(row.deal8_listings_1d) },
];

export default function DailyTable({ rows }: { rows: SeriesPoint[] }) {
  const [page, setPage] = useState(1);
  const newestFirst = [...rows].reverse();
  const lastPage = Math.max(1, Math.ceil(newestFirst.length / PAGE_SIZE));
  const current = Math.min(page, lastPage);
  const shown = newestFirst.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);
  const lastDate = rows[rows.length - 1]?.stat_date;

  return (
    <div>
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full min-w-[44rem] text-left text-sm">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              {COLUMNS.map((column, index) => (
                <th key={column.label} className={`whitespace-nowrap px-4 py-2 font-medium ${index > 0 ? "text-right" : ""}`}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 tabular-nums">
            {shown.map((row) => (
              <tr key={row.stat_date}>
                {COLUMNS.map((column, index) => (
                  <td key={column.label} className={`whitespace-nowrap px-4 py-2 ${index > 0 ? "text-right" : "text-slate-700"}`}>
                    {column.value(row)}
                    {index === 0 && row.stat_date === lastDate && <span className="text-slate-400"> (today so far)</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {lastPage > 1 && (
        <div className="mt-3 flex items-center gap-3 text-sm text-slate-600">
          <button
            type="button"
            disabled={current === 1}
            onClick={() => setPage(current - 1)}
            className="rounded-lg px-3 py-1.5 hover:bg-slate-100 disabled:opacity-40 disabled:hover:bg-transparent"
          >
            Newer
          </button>
          <span>
            Page {current} of {lastPage}
          </span>
          <button
            type="button"
            disabled={current === lastPage}
            onClick={() => setPage(current + 1)}
            className="rounded-lg px-3 py-1.5 hover:bg-slate-100 disabled:opacity-40 disabled:hover:bg-transparent"
          >
            Older
          </button>
        </div>
      )}
    </div>
  );
}
