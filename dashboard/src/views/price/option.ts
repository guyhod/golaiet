import type { ChartOption, Palette } from "../../chart";
import type { PricePoint } from "../../api";

/** The price line against the good-below line. Pure, so it is tested without a canvas. */
export function priceOption(points: PricePoint[], goodBelow: number, palette: Palette): ChartOption {
  const prices = points.map((point) => point.price);
  const low = Math.min(goodBelow, ...prices), high = Math.max(goodBelow, ...prices);
  const margin = Math.max((high - low) * 0.15, high * 0.01);
  return {
    animation: false,
    grid: { left: 64, right: 24, top: 24, bottom: 36 },
    tooltip: { trigger: "axis", backgroundColor: palette.panel, borderColor: palette.line, textStyle: { color: palette.text },
      valueFormatter: (value: unknown) => (typeof value === "number" ? value.toFixed(2) : String(value)) },
    xAxis: { type: "time", axisLine: { lineStyle: { color: palette.line } }, axisLabel: { color: palette.muted }, splitLine: { show: false } },
    yAxis: { type: "value", min: Math.floor(low - margin), max: Math.ceil(high + margin), axisLabel: { color: palette.muted },
      splitLine: { lineStyle: { color: palette.line } } },
    series: [{
      type: "line", name: "price", showSymbol: false, data: points.map((point) => [point.at, point.price]),
      lineStyle: { color: palette.level, width: 2 }, itemStyle: { color: palette.level },
      markLine: { symbol: "none", silent: true, label: { color: palette.text, formatter: `good below ${goodBelow}` },
        lineStyle: { color: palette.text, type: "dashed" }, data: [{ yAxis: goodBelow }] },
    }],
  };
}
