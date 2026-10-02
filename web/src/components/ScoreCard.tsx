import { useId, type ReactNode } from "react";
import { DIMENSIONS } from "../constants";
import { describeScore, formatIntervalRange, formatScore, titleCase } from "../format";
import type { Score } from "../types";
import { Axis, IntervalBar } from "./IntervalBar";

type Props = {
  /** Heading of the card, e.g. "Store score". */
  title: string;
  score: Score;
  /** What the interval covers, under the bars. */
  caption?: ReactNode;
  /** Extra facts beside the score, e.g. table and row counts. */
  meta?: ReactNode;
};

/** Overall score with its interval and the six dimensions as interval bars on a 0–100 axis. */
export function ScoreCard({ title, score, caption, meta }: Props) {
  const titleId = useId();
  const range = formatIntervalRange(score.low, score.high);
  const hasScore = score.overall !== null && score.overall !== undefined;
  return (
    <section className="card score-card" aria-labelledby={titleId}>
      <h2 id={titleId} className="eyebrow">
        {title}
      </h2>
      <div className="score-row">
        <p className="score-big num" aria-label={`${title}: ${describeScore(score.overall, score.low, score.high)}`}>
          {formatScore(score.overall)}
          <small> / 100</small>
        </p>
        <div className="score-meta">
          {hasScore ? (
            <span className="num">
              {range === "full read" ? "every row read · no sampling interval" : `95 % interval ${range}`}
            </span>
          ) : (
            <span>no active checks</span>
          )}
          {meta}
        </div>
      </div>
      <div className="dims" role="list" aria-label="Scores per dimension, with 95 % intervals">
        {DIMENSIONS.map((name) => {
          const d = score.dimensions[name];
          return (
            <div role="listitem" key={name}>
              <IntervalBar
                label={titleCase(name)}
                value={d?.value}
                low={d?.low}
                high={d?.high}
                note={d ? `${d.checks} ${d.checks === 1 ? "check" : "checks"}` : undefined}
              />
            </div>
          );
        })}
        <Axis />
      </div>
      {caption && <p className="caption">{caption}</p>}
    </section>
  );
}
