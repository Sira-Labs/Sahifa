import { formatNumber, formatPercent } from "./format";
import type { MeasurePoint } from "./types";

/** The measures a column's history can hold (spec 024), in the order the page shows them. */
export const MEASURES: { key: string; label: string; share?: boolean }[] = [
  { key: "null_share", label: "Null share", share: true },
  { key: "distinct_share", label: "Distinct share", share: true },
  { key: "blank_share", label: "Blank share", share: true },
  { key: "mean", label: "Mean" },
  { key: "stddev", label: "Standard deviation" },
  { key: "min", label: "Minimum" },
  { key: "max", label: "Maximum" },
  { key: "p01", label: "1st percentile" },
  { key: "p25", label: "25th percentile" },
  { key: "p50", label: "Median" },
  { key: "p75", label: "75th percentile" },
  { key: "p99", label: "99th percentile" },
  { key: "mean_length", label: "Mean length" },
];

/** A measure's value as text: shares as percentages, the rest as numbers. */
export function formatMeasure(value: number | undefined, share?: boolean): string {
  if (value === undefined) return "—";
  return share ? formatPercent(value) : formatNumber(value);
}

export type Series = { key: string; label: string; share?: boolean; values: { point: MeasurePoint; value: number }[] };

/** One series per measure that at least one point has, in the page's order; a point without
 * the measure is left out of its series. */
export function seriesOf(points: MeasurePoint[]): Series[] {
  return MEASURES.map((m) => ({
    ...m,
    values: points.flatMap((point) => {
      const value = point.measures[m.key];
      return value === undefined ? [] : [{ point, value }];
    }),
  })).filter((s) => s.values.length > 0);
}

/** The text alternative of a series' chart: first, newest, lowest and highest value. */
export function describeSeries(s: Series): string {
  const values = s.values.map((v) => v.value);
  const text = (v: number) => formatMeasure(v, s.share);
  const newest = text(values[values.length - 1]!);
  if (values.length === 1) return `${s.label}: ${newest} in the one scan so far. A second scan makes a line.`;
  return (
    `${s.label} over ${values.length} scans: first ${text(values[0]!)}, newest ${newest}, ` +
    `lowest ${text(Math.min(...values))}, highest ${text(Math.max(...values))}.`
  );
}
