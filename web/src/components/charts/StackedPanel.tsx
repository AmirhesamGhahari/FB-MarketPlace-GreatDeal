// One card with two panels that share the date axis and the hover: lines in dollars on top (the first one with a soft fill
// under it), columns (a count) below. Two panels instead of one plot with two scales, so nobody has to guess which axis a shape
// belongs to.
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { compactNumber, formatShortDate, money } from "../../lib/format";
import { ChartCard, RowTooltip, type Headline, type SeriesDef } from "./parts";
import { AXIS, GRID, SURFACE, TICK } from "./theme";

type Row = { stat_date: string } & Record<string, unknown>;
type Props = {
  title: string;
  subtitle?: string;
  headline?: Headline[];
  rows: Row[];
  lines: SeriesDef[]; // the top panel; a line without any value in the rows is left out (and out of the legend)
  bar: SeriesDef; // the bottom panel
  syncId: string;
};

const MARGIN = { top: 10, right: 12, bottom: 0, left: 0 };
const TOP_HEIGHT = 190;
const BOTTOM_HEIGHT = 130;
const count = (value: number) => value.toLocaleString("en-CA");

export default function StackedPanel({ title, subtitle, headline, rows, lines: allLines, bar, syncId }: Props) {
  const lines = allLines.filter((line) => rows.some((row) => typeof row[line.key] === "number"));
  const lastIndex = rows.length - 1;
  const lastDate = rows[lastIndex]?.stat_date ?? "";
  const gradientId = `fill-${syncId}`;
  const items = [
    ...lines.map((line) => ({ label: line.label, color: line.color, value: (row: Row) => (typeof row[line.key] === "number" ? money(row[line.key] as number) : "n/a") })),
    { label: bar.label, color: bar.color, value: (row: Row) => (typeof row[bar.key] === "number" ? count(row[bar.key] as number) : "n/a") },
  ];

  return (
    <ChartCard
      title={title}
      subtitle={subtitle}
      headline={headline}
      legend={[...lines.map((line) => ({ ...line, kind: "line" as const })), { ...bar, kind: "bar" as const }]}
      height={TOP_HEIGHT + BOTTOM_HEIGHT}
      tableRows={[...rows].reverse()}
      tableColumns={[
        { label: "Day", value: (row) => formatShortDate(row.stat_date) },
        ...[...lines, bar].map((series) => ({
          label: series.label,
          value: (row: Row) => {
            const value = row[series.key];
            if (typeof value !== "number") return "n/a";
            return series === bar ? count(value) : money(value);
          },
        })),
      ]}
    >
      <ResponsiveContainer width="100%" height={TOP_HEIGHT}>
        <ComposedChart data={rows} margin={MARGIN} syncId={syncId}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={lines[0]?.color ?? "#2a78d6"} stopOpacity={0.2} />
              <stop offset="1" stopColor={lines[0]?.color ?? "#2a78d6"} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="stat_date" hide />
          <YAxis
            tickFormatter={(v: number) => `$${v.toLocaleString("en-CA")}`}
            tick={TICK}
            tickLine={false}
            axisLine={false}
            width={60}
            domain={["auto", "auto"]}
          />
          <Tooltip cursor={{ stroke: AXIS }} content={(props) => <RowTooltip {...props} rows={rows} items={items} lastDate={lastDate} />} />
          {lines[0] && <Area dataKey={lines[0].key} type="linear" stroke="none" fill={`url(#${gradientId})`} isAnimationActive={false} activeDot={false} legendType="none" tooltipType="none" />}
          {lines.map((line) => (
            <Line
              key={line.key}
              dataKey={line.key}
              name={line.label}
              type="linear"
              stroke={line.color}
              strokeWidth={2.5}
              strokeLinecap="round"
              strokeLinejoin="round"
              isAnimationActive={false}
              dot={(dot) =>
                dot.index === lastIndex ? (
                  <circle key={`end-${line.key}`} cx={dot.cx} cy={dot.cy} r={5} fill={line.color} stroke={SURFACE} strokeWidth={2} />
                ) : (
                  <g key={`none-${line.key}-${dot.index}`} />
                )
              }
              activeDot={{ r: 5, fill: line.color, stroke: SURFACE, strokeWidth: 2 }}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
      <ResponsiveContainer width="100%" height={BOTTOM_HEIGHT}>
        <BarChart data={rows} margin={MARGIN} syncId={syncId}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis
            dataKey="stat_date"
            tickFormatter={formatShortDate}
            tick={TICK}
            tickLine={false}
            axisLine={{ stroke: AXIS }}
            minTickGap={28}
          />
          <YAxis tickFormatter={compactNumber} tick={TICK} tickLine={false} axisLine={false} width={60} allowDecimals={false} tickCount={3} />
          <Tooltip cursor={{ fill: "rgba(11,11,11,0.04)" }} content={() => null} />
          <Bar dataKey={bar.key} name={bar.label} fill={bar.color} fillOpacity={0.9} maxBarSize={18} radius={[5, 5, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
