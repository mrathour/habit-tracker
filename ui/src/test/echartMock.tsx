import type { EChartsCoreOption } from "echarts/core";

import type { ChartClick } from "../dashboard/EChart";
import { charts } from "./chartRegistry";

/** Stands in for ECharts, which needs a real canvas that jsdom doesn't have. */
export function EChart({
  option,
  label,
  onClick,
}: {
  option: EChartsCoreOption;
  label: string;
  height: number;
  onClick?: (click: ChartClick) => void;
}) {
  charts.set(label, { option, onClick });
  return <div className="echart" role="img" aria-label={label} />;
}
