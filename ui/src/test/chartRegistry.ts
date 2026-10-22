import type { EChartsCoreOption } from "echarts/core";

import type { ChartClick } from "../dashboard/EChart";

/** The charts on screen, by label: tests read their options and click them through here. */
export const charts = new Map<
  string,
  { option: EChartsCoreOption; onClick: ((click: ChartClick) => void) | undefined }
>();
