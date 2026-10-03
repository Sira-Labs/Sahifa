import { describeScore, formatIntervalRange, formatScore, type ReadKind } from "../format";

/** A score with its interval inline: "92.7 · 92.3–93.1", "92.7 · full read" or "—". `read` says
 * whether every row was read, where the caller knows it. */
export function ScoreText({
  value,
  low,
  high,
  read,
}: {
  value: number | null | undefined;
  low?: number | null;
  high?: number | null;
  read?: ReadKind;
}) {
  if (value === null || value === undefined) {
    return (
      <span className="num" aria-label="no score, no active checks">
        —
      </span>
    );
  }
  const range = formatIntervalRange(low, high, read);
  return (
    <span className="num score-text" aria-label={describeScore(value, low, high, read)}>
      <b>{formatScore(value)}</b>
      {range && <span className="score-range"> · {range}</span>}
    </span>
  );
}
