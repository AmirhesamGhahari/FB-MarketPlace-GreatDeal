// A line chart over days: one or more series that share one y-axis (same unit), with a hover line and tooltip.
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { compactNumber, formatShortDate, money } from "../../lib/format";
import { ChartCard, TooltipBox, type SeriesDef } from "./parts";
import { AXIS, CHART_HEIGHT, GRID, SURFACE, TICK } from "./theme";

type Row = { stat_date: string } & Record<string, unknown>;
type Props = {
  title: string;
  subtitle?: string;
  rows: Row[];
  series: SeriesDef[];
  format?: (value: number) => string; // for the tooltip and the table; defaults to dollars
  axisFormat?: (value: number) => string;
};

export default function LinePanel({ title, subtitle, rows, series, format = money, axisFormat = compactNumber }: Props) {
  const lastIndex = rows.length - 1;
  const lastDate = rows[lastIndex]?.stat_date ?? "";

  return (
    <ChartCard
      title={title}
      subtitle={subtitle}
      legend={series}
      tableRows={[...rows].reverse()}
      tableColumns={[
        { label: "Day", value: (row) => formatShortDate(row.stat_date) },
        ...series.map((s) => ({
          label: s.label,
          value: (row: Row) => (typeof row[s.key] === "number" ? format(row[s.key] as number) : "n/a"),
        })),
      ]}
    >
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis
            dataKey="stat_date"
            tickFormatter={formatShortDate}
            tick={TICK}
            tickLine={false}
            axisLine={{ stroke: AXIS }}
            minTickGap={28}
          />
          <YAxis
            tickFormatter={(v: number) => (format === money ? `$${v.toLocaleString("en-CA")}` : axisFormat(v))}
            tick={TICK}
            tickLine={false}
            axisLine={false}
            width={60}
            domain={["auto", "auto"]}
          />
          <Tooltip
            cursor={{ stroke: AXIS }}
            content={(props) => <TooltipBox {...props} format={format} lastDate={lastDate} />}
          />
          {series.map((s) => (
            <Line
              key={s.key}
              dataKey={s.key}
              name={s.label}
              type="linear"
              stroke={s.color}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              isAnimationActive={false}
              // a dot (8px, with a ring in the card colour) only on the newest day
              dot={(dot) =>
                dot.index === lastIndex ? (
                  <circle key={`end-${s.key}`} cx={dot.cx} cy={dot.cy} r={4} fill={s.color} stroke={SURFACE} strokeWidth={2} />
                ) : (
                  <g key={`none-${s.key}-${dot.index}`} />
                )
              }
              activeDot={{ r: 4, fill: s.color, stroke: SURFACE, strokeWidth: 2 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
