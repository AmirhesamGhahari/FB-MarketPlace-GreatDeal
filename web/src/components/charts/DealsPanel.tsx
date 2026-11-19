// The cheapest listings of each day (up to 3 per day, from the last 7 days at that time) as dots. Each dot is a real link
// to the Facebook listing.
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, XAxis, YAxis } from "recharts";
import type { SeriesPoint } from "../../lib/api";
import { formatShortDate, money } from "../../lib/format";
import { ChartCard } from "./parts";
import { AXIS, CHART_HEIGHT, GRID, SERIES_COLORS, SURFACE, TICK } from "./theme";

type Dot = { x: number; price: number; url: string | null; day: string };
type Props = { title: string; subtitle?: string; rows: SeriesPoint[] };

export default function DealsPanel({ title, subtitle, rows }: Props) {
  // x is the position of the day in the window (0 = oldest shown), so days without deals stay as gaps.
  const dots: Dot[] = rows.flatMap((row, x) =>
    (row.lowest_3_deals_7d ?? []).map((deal) => ({ x, price: deal.price, url: deal.url, day: row.stat_date })),
  );
  const lastIndex = rows.length - 1;
  const tickEvery = Math.max(1, Math.ceil(rows.length / 8));
  const ticks = rows.map((_, i) => i).filter((i) => (lastIndex - i) % tickEvery === 0);

  return (
    <ChartCard
      title={title}
      subtitle={subtitle}
      tableRows={[...dots].reverse()}
      tableColumns={[
        { label: "Day", value: (dot: Dot) => formatShortDate(dot.day) },
        { label: "Price", value: (dot: Dot) => money(dot.price) },
        { label: "Listing", value: (dot: Dot) => (dot.url ? "On Facebook (link in the chart)" : "n/a") },
      ]}
    >
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <ScatterChart margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
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
          <Scatter
            data={dots}
            isAnimationActive={false}
            shape={(dot: { cx?: number; cy?: number; payload?: Dot }) => {
              const { cx = 0, cy = 0, payload } = dot;
              const href = payload?.url?.startsWith("https://") ? payload.url : undefined;
              const marker = (
                <>
                  {/* a larger invisible circle makes the dot easy to hit */}
                  <circle cx={cx} cy={cy} r={12} fill="transparent" />
                  <circle cx={cx} cy={cy} r={4} fill={SERIES_COLORS[0]} stroke={SURFACE} strokeWidth={2} />
                </>
              );
              return href ? (
                <a href={href} target="_blank" rel="nofollow noopener noreferrer" style={{ cursor: "pointer" }}>
                  <title>{`${money(payload!.price)} on ${formatShortDate(payload!.day)}: open the listing on Facebook`}</title>
                  {marker}
                </a>
              ) : (
                <g>{marker}</g>
              );
            }}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
