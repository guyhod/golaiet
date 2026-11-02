import type { ChartOption, Palette } from "../../chart";
import type { Figure } from "./arrange";

/** A digest's figure as horizontal bars in the order the desk gave them, the value at the bar's end. Pure. */
export function figureOption(figure: Figure, palette: Palette): ChartOption {
  const unit = figure.unit ? ` ${figure.unit}` : "";
  return {
    animation: false,
    grid: { left: 8, right: 72, top: 4, bottom: 4, containLabel: true },
    tooltip: { trigger: "item", backgroundColor: palette.panel, borderColor: palette.line, textStyle: { color: palette.text },
      formatter: (params: unknown) => {
        const { dataIndex } = params as { dataIndex: number };
        const bar = figure.bars[dataIndex];
        return `${bar.label}: ${bar.value}${unit}${bar.note ? `<br/>${bar.note}` : ""}`;
      } },
    xAxis: { type: "value", show: false, max: Math.max(...figure.bars.map((bar) => bar.value)) * 1.05 },
    yAxis: { type: "category", inverse: true, data: figure.bars.map((bar) => bar.label),
      axisLabel: { color: palette.text, fontSize: 13 }, axisLine: { show: false }, axisTick: { show: false } },
    series: [{
      type: "bar", data: figure.bars.map((bar) => bar.value), barMaxWidth: 20,
      itemStyle: { color: palette.level, borderRadius: 3 },
      label: { show: true, position: "right", color: palette.text, formatter: (params: unknown) => `${(params as { value: number }).value}${unit}` },
    }],
  };
}
