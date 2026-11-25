// The cheapest listings of each day (the 5 cheapest posted that day) as dots, over two lines: the 30-day average and the cheapest-25% price as of each day. Hovering or focusing a dot
// shows its details; clicking (or tapping) pins the details with a link that opens the listing on Facebook in a new tab.
import { useEffect, useRef, useState, type MouseEvent } from "react";
import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Scatter, XAxis, YAxis } from "recharts";
import type { SeriesPoint } from "../../lib/api";
import { formatPriceDiff, formatShortDate, money } from "../../lib/format";
import { ChartCard, type Headline } from "./parts";
import { AXIS, GRID, SERIES_COLORS, SURFACE, TICK } from "./theme";

// The cheapest listings of one day. An API that does not send the per-day list yet falls back to the 3 cheapest of the 7 days.
export const dealsOfDay = (row: SeriesPoint) => (row.lowest_5_deals_1d !== undefined ? row.lowest_5_deals_1d : row.lowest_3_deals_7d) ?? [];

type Dot = { id: number; x: number; price: number; url: string | null; day: string; avg: number | null };
type Active = { dot: Dot; cx: number; cy: number; pinned: boolean };
type Props = { title: string; subtitle?: string; headline?: Headline[]; rows: SeriesPoint[] };

export default function DealsPanel({ title, subtitle, headline, rows }: Props) {
  const [active, setActive] = useState<Active | null>(null);
  const box = useRef<HTMLDivElement>(null);
  // Where each dot is drawn (filled in while the chart renders). Hovering and clicking are worked out from these positions
  // instead of from the tiny dot shapes, so the whole area around a dot reacts and a redraw can never swallow a click.
  const positions = useRef(new Map<number, { dot: Dot; cx: number; cy: number }>());

  // Escape closes a pinned card.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setActive(null);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // x is the position of the day in the window (0 = oldest shown), so days without deals stay as gaps.
  const dots: Dot[] = rows.flatMap((row, x) =>
    dealsOfDay(row).map((deal) => ({ id: 0, x, price: deal.price, url: deal.url, day: row.stat_date, avg: row.avg_price_30d })),
  );
  dots.forEach((dot, index) => (dot.id = index));
  // The dot closest to the pointer, if it is within 20 px.
  function nearestDot(event: MouseEvent) {
    const rect = box.current?.getBoundingClientRect();
    if (!rect) return null;
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    let best: { dot: Dot; cx: number; cy: number } | null = null;
    let bestDistance = 20;
    for (const entry of positions.current.values()) {
      const distance = Math.hypot(entry.cx - px, entry.cy - py);
      if (distance <= bestDistance) {
        best = entry;
        bestDistance = distance;
      }
    }
    return best;
  }

  // The two lines, one point per day on the same x positions as the dots.
  const lineRows = rows.map((row, x) => ({ x, avg: row.avg_price_30d, cutoff: row.cutoff_price_cheapest_25pct_30d }));
  // The same colours as the 30-day chart above (average blue, cheapest 25% orange); the dots take the third one.
  const [avgColor, cutoffColor, dotColor] = SERIES_COLORS;
  const legend = [
    { key: "dots", label: "5 cheapest listings of the day", color: dotColor, kind: "dot" as const },
    { key: "avg", label: "30-day average", color: avgColor, kind: "line" as const },
    { key: "cutoff", label: "Cheapest 25% (30 days)", color: cutoffColor, kind: "line" as const },
  ];

  const lastIndex = rows.length - 1;
  const tickEvery = Math.max(1, Math.ceil(rows.length / 8));
  const ticks = rows.map((_, i) => i).filter((i) => (lastIndex - i) % tickEvery === 0);

  // The card sits above the dot, shifted sideways near the edges so it stays inside the chart.
  const width = box.current?.clientWidth ?? 0;
  const side = active && width > 0 ? (active.cx < 130 ? "left" : active.cx > width - 130 ? "right" : "center") : "center";
  const diff = active && active.dot.avg !== null ? active.dot.price - active.dot.avg : null;
  const href = active?.dot.url?.startsWith("https://") ? active.dot.url : undefined;

  return (
    <ChartCard
      title={title}
      subtitle={subtitle}
      headline={headline}
      legend={legend}
      height={270}
      tableRows={[...dots].reverse()}
      tableColumns={[
        { label: "Day", value: (dot: Dot) => formatShortDate(dot.day) },
        { label: "Price", value: (dot: Dot) => money(dot.price) },
        { label: "Listing", value: (dot: Dot) => (dot.url ? "On Facebook (open it from the chart)" : "n/a") },
      ]}
    >
      <div
        ref={box}
        className={`relative h-full ${active ? "cursor-pointer" : ""}`}
        onMouseMove={(event) => {
          const near = nearestDot(event);
          setActive((current) => (current?.pinned ? current : near ? { ...near, pinned: false } : null));
        }}
        onMouseLeave={() => setActive((current) => (current?.pinned ? current : null))}
        onClick={(event) => {
          if ((event.target as Element).closest("[data-dot-card]")) return; // a click inside the card (its link) is left alone
          const near = nearestDot(event);
          setActive(near ? { ...near, pinned: true } : null);
        }}
      >
        <ResponsiveContainer width="100%" height={270}>
          <ComposedChart margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis
              type="number"
              dataKey="x"
              domain={[-0.5, lastIndex + 0.5]}
              ticks={ticks}
              tickFormatter={(i: number) => (rows[i] ? formatShortDate(rows[i].stat_date) : "")}
              tick={TICK}
              tickLine={false}
              axisLine={{ stroke: AXIS }}
            />
            <YAxis
              type="number"
              dataKey="price"
              tickFormatter={(v: number) => `$${v.toLocaleString("en-CA")}`}
              tick={TICK}
              tickLine={false}
              axisLine={false}
              width={60}
              domain={["auto", "auto"]}
            />
            <Line data={lineRows} dataKey="avg" type="linear" stroke={avgColor} strokeWidth={2.5} dot={false} activeDot={false} isAnimationActive={false} connectNulls />
            <Line data={lineRows} dataKey="cutoff" type="linear" stroke={cutoffColor} strokeWidth={2.5} dot={false} activeDot={false} isAnimationActive={false} connectNulls />
            <Scatter
              data={dots}
              isAnimationActive={false}
              shape={(shape: { cx?: number; cy?: number; payload?: Dot }) => {
                const { cx = 0, cy = 0, payload } = shape;
                if (!payload) return <g />;
                positions.current.set(payload.id, { dot: payload, cx, cy });
                const isActive = active?.dot.id === payload.id;
                const show = (pinned: boolean) => setActive({ dot: payload, cx, cy, pinned });
                return (
                  <g
                    tabIndex={0}
                    role="button"
                    aria-label={`${money(payload.price)} on ${formatShortDate(payload.day)}: show details`}
                    style={{ outline: "none" }}
                    // A mouse press must not move the focus: the redraw that follows would replace the dot between the press and
                    // the release, and the browser would never send the click. Keyboard focus still shows the details.
                    onMouseDown={(event) => event.preventDefault()}
                    onFocus={(event) => {
                      if (event.currentTarget.matches(":focus-visible")) {
                        setActive((current) => (current?.pinned ? current : { dot: payload, cx, cy, pinned: false }));
                      }
                    }}
                    onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && show(true)}
                  >
                    {isActive && <circle cx={cx} cy={cy} r={12} fill={dotColor} fillOpacity={0.18} />}
                    <circle cx={cx} cy={cy} r={isActive ? 7 : 5} fill={dotColor} fillOpacity={isActive ? 1 : 0.85} stroke={SURFACE} strokeWidth={2} />
                  </g>
                );
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>

        {active && (
          <div
            data-dot-card
            className={`absolute z-10 w-56 -translate-y-full rounded-lg border border-slate-200 bg-white p-3 text-sm shadow-lg ${
              side === "center" ? "-translate-x-1/2" : side === "right" ? "-translate-x-full" : ""
            } ${active.pinned ? "" : "pointer-events-none"}`}
            style={{ left: active.cx, top: active.cy - 14 }}
            role="status"
          >
            <p className="text-xs text-slate-500">{formatShortDate(active.dot.day)}</p>
            <p className="mt-0.5 text-lg font-semibold text-slate-900">{money(active.dot.price)}</p>
            {diff !== null && (
              <p className={`text-xs font-medium ${diff < 0 ? "text-good" : "text-bad"}`}>{formatPriceDiff(diff)} vs the 30-day average that day</p>
            )}
            {href ? (
              active.pinned ? (
                <a href={href} target="_blank" rel="nofollow noopener noreferrer" className="mt-2 inline-block font-medium">
                  Open on Facebook ↗
                </a>
              ) : (
                <p className="mt-2 text-xs text-slate-400">Click the dot for the link</p>
              )
            ) : null}
          </div>
        )}
      </div>
    </ChartCard>
  );
}
