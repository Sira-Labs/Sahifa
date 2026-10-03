import { formatCount, formatPassShare, titleCase } from "../format";
import type { CheckResult } from "../types";
import { SeverityChip, StatusChip } from "./Chips";
import { Examples } from "./Examples";
import { SqlBlock } from "./SqlBlock";

/** Check results with their pass share and interval, a status chip and the summary. */
export function CheckList({ checks, empty = "No checks." }: { checks: CheckResult[]; empty?: string }) {
  if (checks.length === 0) return <p className="muted">{empty}</p>;
  return (
    <ul className="check-list">
      {checks.map((c) => (
        <li key={c.spec.id} className="check-item">
          <div className="check-head">
            <StatusChip status={c.passed ? "passed" : "failed"} />
            {c.spec.status !== "active" && <StatusChip status={c.spec.status} />}
            <SeverityChip severity={c.spec.severity} />
            <code className="check-type">{c.spec.type}</code>
            <span className="tag">{titleCase(c.spec.dimension)}</span>
          </div>
          <p>{c.summary}</p>
          <p className="num muted text-sm">
            passing {formatPassShare(c.ratio, c.low, c.high)} · {formatCount(c.failed)} of {formatCount(c.evaluated)} failed
          </p>
          {!c.passed && (c.examples.length > 0 || c.examples_skipped) && <Examples items={c.examples} skipped={c.examples_skipped} />}
          {!c.passed && c.sql && <SqlBlock sql={c.sql} />}
          {!c.passed && c.next_step && (
            <p className="next-step text-sm">
              <strong>Next step: </strong>
              {c.next_step}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}
