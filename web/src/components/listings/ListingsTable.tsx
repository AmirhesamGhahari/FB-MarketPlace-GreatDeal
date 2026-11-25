// The all-listings table. It loads the product's listings in the browser, from the static file written at build time
// (/data/listings/{category}/{slug}.json) and, if there is none, from the live API, then filters, sorts and pages them itself, so clicking
// never makes another request.
import { useEffect, useState } from "react";
import { getListingsAll, getListingsFile, type ListingRow } from "../../lib/api";
import { formatDate, formatDateTime, formatPriceDiff, money } from "../../lib/format";

const PERIODS = [1, 3, 7, 15, 30] as const;
const PAGE_SIZES = [10, 25, 50, 100] as const;
const SORTS = {
  newest: "Newest first",
  price_asc: "Lowest price",
  price_desc: "Highest price",
  saving: "Biggest saving vs average",
} as const;
type SortKey = keyof typeof SORTS;

// Rows without a number (null) go last when sorting by saving.
const bySaving = (a: ListingRow, b: ListingRow) => (a.price_diff_30d ?? Infinity) - (b.price_diff_30d ?? Infinity);
const SORTERS: Record<SortKey, ((a: ListingRow, b: ListingRow) => number) | null> = {
  newest: null, // the API already sends newest first
  price_asc: (a, b) => a.price - b.price,
  price_desc: (a, b) => b.price - a.price,
  saving: bySaving,
};

function ago(days: number) {
  return days === 0 ? "Today" : days === 1 ? "1 day ago" : `${days} days ago`;
}

function DiffBadge({ diff }: { diff: number | null }) {
  if (diff === null) return <span className="text-slate-400">n/a</span>;
  const style = diff < 0 ? "bg-good-bg text-good" : diff > 0 ? "bg-bad-bg text-bad" : "bg-slate-100 text-slate-600";
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${style}`}>
      {formatPriceDiff(diff)}
    </span>
  );
}

// Page numbers with gaps: 1 … 4 5 [6] 7 8 … 20
function pageList(current: number, last: number): (number | "gap")[] {
  const wanted = new Set([1, last, current - 1, current, current + 1].filter((n) => n >= 1 && n <= last));
  const sorted = [...wanted].sort((a, b) => a - b);
  const out: (number | "gap")[] = [];
  sorted.forEach((n, i) => {
    if (i > 0 && n - sorted[i - 1] > 1) out.push("gap");
    out.push(n);
  });
  return out;
}

type Props = {
  slug: string;
  categoryKey: string; // the category in its URL form (apple-watch), the folder of the static listings file
  defaultSort?: SortKey; // "price_asc" turns the table into a list of the cheapest listings (the deals explorer)
  defaultDays?: number;
  defaultPageSize?: number;
};

export default function ListingsTable({ slug, categoryKey, defaultSort = "newest", defaultDays = 15, defaultPageSize = 25 }: Props) {
  const [rows, setRows] = useState<ListingRow[] | null>(null);
  const [asOf, setAsOf] = useState<string | null>(null); // when the listings were built
  const [viaApi, setViaApi] = useState(false); // true while the slower live API is used
  const [failed, setFailed] = useState<false | "missing" | "error">(false);
  const [attempt, setAttempt] = useState(0);
  const [days, setDays] = useState<number>(defaultDays);
  const [sort, setSort] = useState<SortKey>(defaultSort);
  const [pageSize, setPageSize] = useState<number>(defaultPageSize);
  const [page, setPage] = useState(1);

  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    setRows(null);
    setViaApi(false);
    const show = (res: { data_as_of: string; data: ListingRow[] }) => {
      if (cancelled) return;
      setRows(res.data);
      setAsOf(res.data_as_of);
    };
    getListingsFile(categoryKey, slug)
      .then((file) => {
        if (file || cancelled) return file && show(file);
        // No static file for this model: ask the live API instead.
        setViaApi(true);
        return getListingsAll(slug).then(show);
      })
      // "API 404" means the live API does not know the all-listings address (it has not been updated yet).
      .catch((error) => !cancelled && setFailed(String(error).includes("API 404") ? "missing" : "error"));
    return () => {
      cancelled = true;
    };
  }, [categoryKey, slug, attempt]);

  if (failed) {
    return (
      <div className="rounded-xl border border-slate-200 p-6 text-slate-600">
        <p>
          {failed === "missing"
            ? "The listings service has not been updated yet, so the full list is not available right now."
            : "The listings could not be loaded. Please try again in a moment."}
        </p>
        <button
          type="button"
          onClick={() => setAttempt(attempt + 1)}
          className="mt-3 rounded-full bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
        >
          Try again
        </button>
      </div>
    );
  }
  if (rows === null) {
    return (
      <div className="rounded-xl border border-slate-200 p-6 text-slate-600" role="status">
        <p className="font-medium">Loading listings…</p>
        {viaApi && (
          <p className="mt-1 text-sm text-slate-500">
            This can take up to 30 seconds after a quiet period while the database wakes up.
          </p>
        )}
      </div>
    );
  }

  const inPeriod = rows.filter((row) => row.days_ago < days);
  const sorter = SORTERS[sort];
  const sorted = sorter ? [...inPeriod].sort(sorter) : inPeriod;
  const lastPage = Math.max(1, Math.ceil(sorted.length / pageSize));
  const current = Math.min(page, lastPage);
  const shown = sorted.slice((current - 1) * pageSize, current * pageSize);
  const from = sorted.length === 0 ? 0 : (current - 1) * pageSize + 1;
  const to = (current - 1) * pageSize + shown.length;

  const choose = <T,>(setter: (value: T) => void, value: T) => {
    setter(value);
    setPage(1);
  };
  const th = "px-4 py-3 font-medium whitespace-nowrap";
  const td = "px-4 py-3 align-top";

  return (
    <div>
      {asOf && <p className="mb-3 text-sm text-slate-500">Listings as of {formatDateTime(asOf)}</p>}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div role="group" aria-label="Period" className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-sm text-slate-500">Listed in the last</span>
          {PERIODS.map((period) => (
            <button
              key={period}
              type="button"
              aria-pressed={days === period}
              onClick={() => choose(setDays, period)}
              className={`rounded-full px-3 py-1 text-sm font-medium ${
                days === period ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
              }`}
            >
              {period === 1 ? "1 day" : `${period} days`}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-500">
          Sort by
          <select
            value={sort}
            onChange={(event) => choose(setSort, event.target.value as SortKey)}
            className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
          >
            {Object.entries(SORTS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-500">
          Rows per page
          <select
            value={pageSize}
            onChange={(event) => choose(setPageSize, Number(event.target.value))}
            className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
          >
            {[...new Set([...PAGE_SIZES, defaultPageSize])]
              .sort((a, b) => a - b)
              .map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
          </select>
        </label>
      </div>

      <p className="mt-4 text-sm text-slate-500" aria-live="polite">
        {sorted.length === 0
          ? "No listings in this period."
          : `Showing ${from}-${to} of ${sorted.length.toLocaleString("en-CA")} listings`}
      </p>

      {sorted.length > 0 && (
        <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full min-w-[56rem] text-left text-sm">
            <caption className="sr-only">Listings, {SORTS[sort].toLowerCase()}</caption>
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className={th}>Listing</th>
                <th className={`${th} text-right`}>Price</th>
                <th className={th}>vs 30-day avg</th>
                <th className={th}>Condition</th>
                <th className={th}>Storage</th>
                <th className={th}>City</th>
                <th className={th}>Listed</th>
                <th className={th}>
                  <span className="sr-only">Link</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {shown.map((row) => (
                <tr key={row.fb_listing_id}>
                  <td className={`${td} max-w-xs font-medium text-slate-900`}>{row.title ?? "Untitled listing"}</td>
                  <td className={`${td} whitespace-nowrap text-right font-semibold tabular-nums`}>{money(row.price)}</td>
                  <td className={td}>
                    <DiffBadge diff={row.price_diff_30d} />
                  </td>
                  <td className={`${td} text-slate-600`}>
                    {row.condition && row.condition !== "Unknown" ? row.condition : "—"}
                  </td>
                  <td className={`${td} whitespace-nowrap text-slate-600`}>
                    {row.storage_gb ? `${row.storage_gb} GB` : "—"}
                  </td>
                  <td className={`${td} text-slate-600`}>{row.location_city ?? "—"}</td>
                  <td className={`${td} whitespace-nowrap text-slate-600`}>
                    {formatDate(row.listed_at)}
                    <span className="block text-xs text-slate-400">{ago(row.days_ago)}</span>
                  </td>
                  <td className={`${td} whitespace-nowrap`}>
                    {row.listing_url?.startsWith("https://") && (
                      <a href={row.listing_url} target="_blank" rel="nofollow noopener noreferrer">
                        View on Facebook
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {lastPage > 1 && (
        <nav aria-label="Pages" className="mt-4 flex flex-wrap items-center gap-1">
          <button
            type="button"
            disabled={current === 1}
            onClick={() => setPage(current - 1)}
            className="rounded-lg px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100 disabled:opacity-40 disabled:hover:bg-transparent"
          >
            Previous
          </button>
          {pageList(current, lastPage).map((item, index) =>
            item === "gap" ? (
              <span key={`gap-${index}`} className="px-1 text-slate-400" aria-hidden="true">
                …
              </span>
            ) : (
              <button
                key={item}
                type="button"
                aria-current={item === current ? "page" : undefined}
                onClick={() => setPage(item)}
                className={`min-w-9 rounded-lg px-3 py-1.5 text-sm ${
                  item === current ? "bg-brand-600 font-medium text-white" : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                {item}
              </button>
            ),
          )}
          <button
            type="button"
            disabled={current === lastPage}
            onClick={() => setPage(current + 1)}
            className="rounded-lg px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100 disabled:opacity-40 disabled:hover:bg-transparent"
          >
            Next
          </button>
        </nav>
      )}
    </div>
  );
}
