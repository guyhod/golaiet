import { expect, it } from "vitest";
import { figureOption } from "./figure";

const palette = { text: "#fff", muted: "#999", line: "#333", panel: "#111", level: "#2563eb" };

it("draws the bars in the desk's order with the unit at the end", () => {
  const option = figureOption({ title: "מנדטים", unit: "מנדטים", bars: [{ label: "אייזנקוט", value: 48, note: "ליברמן, גולן" }, { label: "נתניהו", value: 53 }] }, palette) as {
    yAxis: { data: string[] }; series: { data: number[]; label: { formatter: (p: unknown) => string } }[]; tooltip: { formatter: (p: unknown) => string }; xAxis: { max: number };
  };
  expect(option.yAxis.data).toEqual(["אייזנקוט", "נתניהו"]);
  expect(option.series[0].data).toEqual([48, 53]);
  expect(option.series[0].label.formatter({ value: 48 })).toBe("48 מנדטים");
  expect(option.tooltip.formatter({ dataIndex: 0 })).toBe("אייזנקוט: 48 מנדטים<br/>ליברמן, גולן");
  expect(option.xAxis.max).toBeCloseTo(55.65, 2);
});
