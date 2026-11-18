import { describeSeries, formatMeasure, type Series } from "../measures";

const WIDTH = 240;
const HEIGHT = 56;
const PAD = 6;

/** Where each value of the series sits in the chart: evenly along x, scaled along y. A flat
 * series runs through the middle. */
export function chartPoints(values: number[]): { x: number; y: number }[] {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const step = values.length > 1 ? (WIDTH - 2 * PAD) / (values.length - 1) : 0;
  return values.map((v, i) => ({
    x: values.length > 1 ? PAD + i * step : WIDTH / 2,
    y: span === 0 ? HEIGHT / 2 : HEIGHT - PAD - ((v - min) / span) * (HEIGHT - 2 * PAD),
  }));
}

/** One measure over the scans: its newest value, a small line with a mark per scan, and the
 * range. The chart is an image with a text alternative; the numbers are in the table below. */
export function MeasureChart({ series }: { series: Series }) {
  const values = series.values.map((v) => v.value);
  const points = chartPoints(values);
  const text = (v: number) => formatMeasure(v, series.share);
  return (
    <li className="card measure-card">
      <p className="eyebrow">{series.label}</p>
      <p className="measure-now num">{text(values[values.length - 1]!)}</p>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={describeSeries(series)} className="measure-chart">
        {points.length > 1 && <polyline points={points.map((p) => `${p.x},${p.y}`).join(" ")} />}
        {points.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={i === points.length - 1 ? 3 : 1.75} />
        ))}
      </svg>
      <p className="muted text-sm num">
        {values.length === 1 ? "One scan so far" : `${text(Math.min(...values))} to ${text(Math.max(...values))} over ${values.length} scans`}
      </p>
    </li>
  );
}
