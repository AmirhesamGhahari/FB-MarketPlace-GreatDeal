// The chart on a model's overview page: the last 15 days, price and listings per day, with the average of the 5 cheapest
// listings of each day as a second line.
import type { SeriesPoint } from "../../lib/api";
import { money } from "../../lib/format";
import StackedPanel from "./StackedPanel";
import { SERIES_COLORS } from "./theme";

const [blue, orange] = SERIES_COLORS;

export default function OverviewChart({ series, title = "Average asking price and listings per day, last 15 days" }: { series: SeriesPoint[]; title?: string }) {
  const rows = series.slice(-15);
  const full = rows.slice(0, -1); // the newest day is only partly over
  const average = full.filter((day) => typeof day.listings_1d === "number");
  const perDay = average.length === 0 ? null : average.reduce((sum, day) => sum + (day.listings_1d ?? 0), 0) / average.length;
  const prices = rows.filter((day) => typeof day.avg_price_1d === "number");
  const first = prices[0]?.avg_price_1d ?? null;
  const last = prices[prices.length - 1]?.avg_price_1d ?? null;
  const change = first && last ? ((last - first) / first) * 100 : null;
  const cheap = rows.filter((day) => typeof day.lowest_5_avg_1d === "number");

  return (
    <StackedPanel
      title={title}
      subtitle={
        cheap.length > 0
          ? "The blue line is the average asking price of each day, the orange line the average of that day's 5 cheapest listings, and the columns the number of listings posted that day."
          : "The line is the average asking price of each day and the columns are the number of listings posted that day."
      }
      syncId="overview"
      headline={[
        { label: "Latest daily average", value: last === null ? "n/a" : money(last) },
        {
          label: "Change over 15 days",
          value: change === null ? "n/a" : `${change > 0 ? "+" : ""}${change.toFixed(1)}%`,
          tone: change === null ? undefined : change < 0 ? "good" : change > 0 ? "bad" : undefined,
        },
        { label: "Listings per day", value: perDay === null ? "n/a" : perDay.toFixed(0), hint: cheap.length === 0 ? undefined : "full days" },
      ]}
      rows={rows}
      lines={[
        { key: "avg_price_1d", label: "Average asking price", color: blue },
        { key: "lowest_5_avg_1d", label: "Average of the 5 cheapest", color: orange },
      ]}
      bar={{ key: "listings_1d", label: "Listings per day", color: "#1baf7a" }}
    />
  );
}
