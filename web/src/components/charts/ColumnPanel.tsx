// A column chart over days for one count (for example listings per day). Thin columns with rounded tops.
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { compactNumber, formatShortDate } from "../../lib/format";
import { ChartCard, TooltipBox } from "./parts";
import { AXIS, CHART_HEIGHT, GRID, SERIES_COLORS, TICK } from "./theme";

type Row = { stat_date: string } & Record<string, unknown>;
type Props = { title: string; subtitle?: string; rows: Row[]; dataKey: string; label: string };

const count = (value: number) => value.toLocaleString("en-CA");

export default function ColumnPanel({ title, subtitle, rows, dataKey, label }: Props) {
  const lastDate = rows[rows.length - 1]?.stat_date ?? "";
  return (
    <ChartCard
      title={title}
      subtitle={subtitle}
      tableRows={[...rows].reverse()}
      tableColumns={[
        { label: "Day", value: (row) => formatShortDate(row.stat_date) },
        { label, value: (row) => (typeof row[dataKey] === "number" ? count(row[dataKey] as number) : "n/a") },
      ]}
    >
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis
            dataKey="stat_date"
            tickFormatter={formatShortDate}
            tick={TICK}
            tickLine={false}
            axisLine={{ stroke: AXIS }}
            minTickGap={28}
          />
          <YAxis tickFormatter={compactNumber} tick={TICK} tickLine={false} axisLine={false} width={52} allowDecimals={false} />
          <Tooltip
            cursor={{ fill: "rgba(11,11,11,0.04)" }}
            content={(props) => <TooltipBox {...props} format={count} lastDate={lastDate} />}
          />
          <Bar
            dataKey={dataKey}
            name={label}
            fill={SERIES_COLORS[0]}
            maxBarSize={20}
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
