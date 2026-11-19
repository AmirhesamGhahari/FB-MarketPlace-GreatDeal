// Pieces shared by every chart: the card around a chart (title, legend, table view), the hover tooltip, and a hook that
// tells us when we are running in the browser.
import { useEffect, useState, type ReactNode } from "react";
import { formatShortDate } from "../../lib/format";
import { CHART_HEIGHT } from "./theme";

export type SeriesDef = { key: string; label: string; color: string };
export type TableColumn = { label: string; value: (row: any) => string };

// False while the page is built on the server and on the first browser render, then true. Recharts needs a real browser
// to measure its width, so the chart itself waits for this, while the title, legend and table are in the HTML from the start.
function useMounted() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted;
}

type ChartCardProps = {
  title: string;
  subtitle?: string;
  legend?: SeriesDef[]; // shown only for two or more series; a single series is named by the title
  tableColumns: TableColumn[];
  tableRows: unknown[];
  children: ReactNode;
};

export function ChartCard({ title, subtitle, legend, tableColumns, tableRows, children }: ChartCardProps) {
  const mounted = useMounted();
  return (
    <figure className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <figcaption>
        <h3 className="text-base font-semibold tracking-tight text-slate-900">{title}</h3>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
        {legend && legend.length > 1 && (
          <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-600">
            {legend.map((item) => (
              <li key={item.key} className="flex items-center gap-2">
                <span className="inline-block h-0.5 w-4 rounded" style={{ background: item.color }} aria-hidden="true" />
                {item.label}
              </li>
            ))}
          </ul>
        )}
      </figcaption>
      <div className="mt-4" style={{ height: CHART_HEIGHT }}>
        {mounted ? children : null}
      </div>
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-slate-500 hover:text-slate-700">View data as a table</summary>
        <div className="mt-2 max-h-72 overflow-auto rounded-lg border border-slate-200">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-slate-500">
              <tr>
                {tableColumns.map((column) => (
                  <th key={column.label} className="px-3 py-2 font-medium">
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 tabular-nums">
              {tableRows.map((row, index) => (
                <tr key={index}>
                  {tableColumns.map((column) => (
                    <td key={column.label} className="px-3 py-1.5 text-slate-700">
                      {column.value(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

type TooltipItem = { dataKey?: unknown; name?: string | number; value?: unknown; color?: string };
type TooltipBoxProps = {
  active?: boolean;
  payload?: ReadonlyArray<TooltipItem>;
  label?: string | number;
  format: (value: number) => string;
  lastDate: string; // the newest day is only partly over, so the tooltip says so
};

// The box that follows the mouse: the date, then one row per series with the value first and the name second.
export function TooltipBox({ active, payload, label, format, lastDate }: TooltipBoxProps) {
  if (!active || !payload || payload.length === 0) return null;
  const day = String(label);
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-md">
      <p className="font-medium text-slate-600">
        {formatShortDate(day)}
        {day === lastDate && " (today so far)"}
      </p>
      <ul className="mt-1 space-y-0.5">
        {payload.map((item) =>
          typeof item.value === "number" ? (
            <li key={String(item.dataKey)} className="flex items-center gap-2">
              <span className="inline-block h-0.5 w-3 rounded" style={{ background: item.color }} aria-hidden="true" />
              <span className="text-slate-500">{item.name}</span>
              <span className="ml-auto pl-4 font-semibold tabular-nums text-slate-900">{format(item.value)}</span>
            </li>
          ) : null,
        )}
      </ul>
    </div>
  );
}
