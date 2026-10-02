import { useId, useState } from "react";
import { formatCount, formatNumber, formatPercent, titleCase, worstDimension } from "../format";
import type { CheckResult, ColumnProfile, ColumnReport } from "../types";
import { CheckList } from "./CheckList";
import { ScoreText } from "./ScoreText";

const COLUMNS = 8;

/** Profile measures worth showing, in reading order; null ones are left out. */
function profileFacts(p: ColumnProfile): [string, string][] {
  const facts: [string, string | null][] = [
    ["Physical type", p.physical_type],
    ["Declared not null", p.declared_not_null ? "yes" : "no"],
    ["Rows read", formatCount(p.rows)],
    ["Nulls", formatCount(p.nulls)],
    ["Blanks", p.blanks === null ? null : formatCount(p.blanks)],
    ["Distinct", p.distinct === null ? null : formatCount(p.distinct)],
    ["Semantic share", p.semantic_share === null ? null : formatPercent(p.semantic_share)],
    ["Min", p.min === null ? null : formatNumber(p.min)],
    ["Max", p.max === null ? null : formatNumber(p.max)],
    ["Mean", p.mean === null ? null : formatNumber(p.mean)],
    ["Std. deviation", p.stddev === null ? null : formatNumber(p.stddev)],
    ["MAD", p.mad === null ? null : formatNumber(p.mad)],
    ["Zeros", p.zeros === null ? null : formatCount(p.zeros)],
    ["Negatives", p.negatives === null ? null : formatCount(p.negatives)],
    ["Min length", p.min_length === null ? null : formatCount(p.min_length)],
    ["Max length", p.max_length === null ? null : formatCount(p.max_length)],
    ["Mean length", p.mean_length === null ? null : formatNumber(p.mean_length)],
    ["Leading or trailing space", p.whitespace === null ? null : formatCount(p.whitespace)],
    ["Non-printing", p.non_printing === null ? null : formatCount(p.non_printing)],
    ["Numeric-like", p.numeric_like === null ? null : formatCount(p.numeric_like)],
    ["Date-like", p.date_like === null ? null : formatCount(p.date_like)],
    ["Leading-zero numbers", p.leading_zero_numbers === null ? null : formatCount(p.leading_zero_numbers)],
    ["In the future", p.future === null ? null : formatCount(p.future)],
    ["Before 1900", p.before_1900 === null ? null : formatCount(p.before_1900)],
    ["After 2200", p.after_2200 === null ? null : formatCount(p.after_2200)],
    ["Newest", p.newest],
  ];
  for (const [q, v] of Object.entries(p.quantiles ?? {})) facts.push([q, formatNumber(v)]);
  return facts.filter((f): f is [string, string] => f[1] !== null && f[1] !== undefined);
}

/** A list of value counts (top values, patterns) as text. */
function ValueList({ title, items, truncated }: { title: string; items: ColumnProfile["top"]; truncated?: boolean }) {
  if (items.length === 0) return null;
  return (
    <div className="min-w-0">
      <h4 className="eyebrow">{title}</h4>
      <ul className="value-list">
        {items.map((v, i) => (
          <li key={i}>
            {v.value === null ? <span className="null-value">null</span> : <code className="value">{v.value}</code>}
            <span className="num muted">{formatCount(v.count)}</span>
          </li>
        ))}
      </ul>
      {truncated && <p className="muted text-sm">More values exist.</p>}
    </div>
  );
}

/** One column of the asset report: a summary row and, expanded, its profile and checks. */
export function ColumnRow({ column, checks }: { column: ColumnReport; checks: CheckResult[] }) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const p = column.profile;
  const worst = worstDimension(column.score);
  const failing = checks.filter((c) => !c.passed).length;

  return (
    <>
      <tr className={open ? "is-open" : undefined}>
        <th scope="row" data-label="Column">
          <button type="button" className="row-toggle" aria-expanded={open} aria-controls={detailId} onClick={() => setOpen((o) => !o)}>
            <span aria-hidden="true" className="caret">
              ▸
            </span>
            <code>{p.name}</code>
            <span className="sr-only">{open ? ", hide profile and checks" : ", show profile and checks"}</span>
          </button>
        </th>
        <td data-label="Type">{p.logical_type}</td>
        <td data-label="Role">{titleCase(p.role)}</td>
        <td data-label="Semantic type">{p.semantic_type ?? "—"}</td>
        <td data-label="Nulls" className="num">
          {p.rows ? formatPercent(p.nulls / p.rows) : "—"}
        </td>
        <td data-label="Distinct" className="num">
          {formatCount(p.distinct)}
        </td>
        <td data-label="Score">
          <ScoreText value={column.score.overall} low={column.score.low} high={column.score.high} />
        </td>
        <td data-label="Worst dimension">
          {worst ? (
            <>
              {titleCase(worst.name)} <span className="num muted">{worst.value.toFixed(1)}</span>
            </>
          ) : (
            "—"
          )}
          {failing > 0 && <span className="muted text-sm"> · {failing} failing</span>}
        </td>
      </tr>
      <tr id={detailId} className="detail-row" hidden={!open}>
        <td colSpan={COLUMNS}>
          {open && (
            <div className="detail">
              <dl className="profile-grid">
                {profileFacts(p).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd className="num">{v}</dd>
                  </div>
                ))}
              </dl>
              <div className="detail-lists">
                <ValueList title="Top values" items={p.top} truncated={p.top_truncated} />
                <ValueList title="Patterns" items={p.patterns} />
              </div>
              <h4 className="eyebrow">Checks on this column</h4>
              <CheckList checks={checks} empty="No checks on this column." />
            </div>
          )}
        </td>
      </tr>
    </>
  );
}
