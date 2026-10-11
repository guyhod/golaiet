// Apache ECharts (Apache-2.0), loaded piecewise: each view registers the
// chart types it draws, and the colours come from the CSS tokens so a chart
// matches the wall. <Chart> owns one chart for its element: init on mount,
// setOption on every change, resize with the element, dispose on unmount.
import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { GridComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";

echarts.use([GridComponent, MarkLineComponent, TooltipComponent, CanvasRenderer]);

export { echarts };
export type ChartOption = EChartsCoreOption;

export type Palette = { text: string; muted: string; line: string; panel: string; level: string };

/** The CSS tokens as a chart sees them; `level` is the colour of the given level rank, as the tiles use it. */
export function paletteOf(levelRank: number): Palette {
  const style = getComputedStyle(document.documentElement);
  const token = (name: string) => style.getPropertyValue(name).trim();
  return { text: token("--text"), muted: token("--muted"), line: token("--line"), panel: token("--panel"),
    level: token(levelRank < 0 ? "--lvl-none" : `--lvl-${levelRank}`) };
}

export function Chart({ option, className }: { option: ChartOption; className?: string }) {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!element.current) return;
    chart.current = echarts.init(element.current, undefined, { renderer: "canvas" });
    const observer = new ResizeObserver(() => chart.current?.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, true);
  }, [option]);

  return <div className={className} ref={element} />;
}
