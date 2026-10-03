import { describeScore, formatIntervalRange, formatScore, type ReadKind } from "../format";

type Scale = { min?: number; max?: number };

/** Percentage position of `v` on the scale, clamped to the track. */
function position(v: number, min: number, max: number): number {
  return Math.min(100, Math.max(0, ((v - min) / (max - min)) * 100));
}

type Props = Scale & {
  label: string;
  value: number | null | undefined;
  low?: number | null;
  high?: number | null;
  /** Shown after the label for screen readers and on hover, e.g. "4 checks". */
  note?: string;
  /** Whether every row was read, where known; only then is a zero-width interval a full read. */
  read?: ReadKind;
};

/** One labelled bar: a light fill to the score, the 95 % interval as a solid segment and a tick
 * at the value; the numbers beside it read "92.7 · 92.3–93.1". A missing score reads "—" with
 * "no active checks". */
export function IntervalBar({ label, value, low, high, note, read, min = 0, max = 100 }: Props) {
  const has = value !== null && value !== undefined;
  const hasInterval = has && low !== null && low !== undefined && high !== null && high !== undefined;
  const range = formatIntervalRange(low, high, read);
  return (
    <div className="dim-row" title={note}>
      <span className="dim-name">{label}</span>
      <span className="track" role="img" aria-label={`${label}: ${describeScore(value, low, high, read)}${note ? `, ${note}` : ""}`}>
        {has && <span className="track-fill" style={{ width: `${position(value, min, max)}%` }} />}
        {hasInterval && (
          <span
            className="track-ci"
            style={{ left: `${position(low, min, max)}%`, width: `${position(high, min, max) - position(low, min, max)}%` }}
          />
        )}
        {has && <span className="track-mark" style={{ left: `${position(value, min, max)}%` }} />}
      </span>
      <span className="dim-val num">
        {has ? (
          <>
            <b>{formatScore(value)}</b>
            {range && ` · ${range}`}
          </>
        ) : (
          <>
            <b>—</b> no active checks
          </>
        )}
      </span>
    </div>
  );
}

/** The labelled axis under a stack of bars. */
export function Axis({ min = 0, max = 100, ticks = [0, 25, 50, 75, 100] }: Scale & { ticks?: number[] }) {
  return (
    <div className="dim-row axis" aria-hidden="true">
      <span />
      <span className="axis-ticks num">
        {ticks.map((t) => (
          <span key={t} style={{ left: `${position(t, min, max)}%` }}>
            {t}
          </span>
        ))}
      </span>
      <span />
    </div>
  );
}
