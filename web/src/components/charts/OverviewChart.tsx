// The one small fixed chart on a product's overview page: the last 15 days, no filters.
import type { SeriesPoint } from "../../lib/api";
import LinePanel from "./LinePanel";
import { SERIES_COLORS } from "./theme";

export default function OverviewChart({ series, title = "Average asking price, last 15 days" }: { series: SeriesPoint[]; title?: string }) {
  return (
    <LinePanel
      title={title}
      subtitle="The daily average moves up and down; the 7-day average shows the trend."
      rows={series.slice(-15)}
      series={[
        { key: "avg_price_1d", label: "Daily average", color: SERIES_COLORS[0] },
        { key: "avg_price_7d", label: "7-day average", color: SERIES_COLORS[1] },
      ]}
    />
  );
}
