import { BarChart, HeatmapChart, LineChart } from "echarts/charts";
import {
  AriaComponent,
  CalendarComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

// Only the pieces the dashboard uses, so the single-file bundle stays small.
echarts.use([
  BarChart,
  LineChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  CalendarComponent,
  VisualMapComponent,
  AriaComponent,
  CanvasRenderer,
]);

export interface ChartClick {
  dataIndex: number;
  /** For the calendar: [date, minutes]. */
  value: unknown;
}

/**
 * One ECharts chart. It follows its container's size, and redraws when the option changes.
 * The visible label is for screen readers; every chart also offers a table (see ChartCard).
 */
export function EChart({
  option,
  label,
  height,
  onClick,
}: {
  option: echarts.EChartsCoreOption;
  label: string;
  height: number;
  onClick?: (click: ChartClick) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const clickRef = useRef(onClick);

  useEffect(() => {
    clickRef.current = onClick;
  }, [onClick]);

  useEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const instance = echarts.init(element, null, { renderer: "canvas" });
    chart.current = instance;
    instance.on("click", (params) => {
      clickRef.current?.({ dataIndex: params.dataIndex, value: params.value });
    });
    const observer = new ResizeObserver(() => {
      instance.resize();
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={ref} className="echart" role="img" aria-label={label} style={{ height }} />;
}
