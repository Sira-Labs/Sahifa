import { Link } from "@tanstack/react-router";
import { assetColumn, formatCount, formatFailedShare, titleCase } from "../format";
import type { Finding } from "../types";
import { SeverityChip } from "./Chips";
import { Examples } from "./Examples";
import { SqlBlock } from "./SqlBlock";

/** One finding: what is wrong, where, how much (failed of evaluated with the interval), example
 * values, the SQL and the next step. */
export function FindingCard({ finding, scanId }: { finding: Finding; scanId: string }) {
  const where = assetColumn(finding.asset, finding.column);
  return (
    <article className="card finding-card" aria-label={`${titleCase(finding.severity)} finding: ${finding.summary}`}>
      <div className="finding-head">
        <SeverityChip severity={finding.severity} />
        <span className="tag">{titleCase(finding.dimension)}</span>
        {finding.title && finding.title !== finding.check_type && <span className="muted text-sm">{finding.title}</span>}
      </div>
      <h3 className="finding-summary">{finding.summary}</h3>
      <dl className="facts">
        <div>
          <dt>Check</dt>
          <dd>
            <code>{finding.check_id}</code>
          </dd>
        </div>
        <div>
          <dt>Where</dt>
          <dd>
            <Link to="/scans/$scanId/assets/$asset" params={{ scanId, asset: finding.asset }} className="code-link">
              {where}
            </Link>
          </dd>
        </div>
        <div>
          <dt>Failed</dt>
          <dd className="num">
            {formatCount(finding.failed)} of {formatCount(finding.evaluated)} ·{" "}
            <span className="nowrap">{formatFailedShare(finding.ratio, finding.low, finding.high)}</span>
          </dd>
        </div>
      </dl>
      <Examples items={finding.examples} />
      {finding.sql && <SqlBlock sql={finding.sql} />}
      {finding.next_step && (
        <p className="next-step">
          <strong>Next step: </strong>
          {finding.next_step}
        </p>
      )}
    </article>
  );
}
