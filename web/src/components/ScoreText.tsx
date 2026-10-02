import { describeScore, formatIntervalRange, formatScore } from "../format";

/** A score with its interval inline: "92.7 · 92.3–93.1", "92.7 · full read" or "—". */
export function ScoreText({ value, low, high }: { value: number | null | undefined; low?: number | null; high?: number | null }) {
  if (value === null || value === undefined) {
    return (
      <span className="num" aria-label="no score, no active checks">
        —
      </span>
    );
  }
  const range = formatIntervalRange(low, high);
  return (
    <span className="num score-text" aria-label={describeScore(value, low, high)}>
      <b>{formatScore(value)}</b>
      {range && <span className="score-range"> · {range}</span>}
    </span>
  );
}
