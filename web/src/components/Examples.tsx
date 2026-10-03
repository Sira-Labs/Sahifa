import { formatCount } from "../format";
import type { ValueCount } from "../types";

/** Too many checks failed on the table for each to get an example query (spec 013). */
export const EXAMPLES_SKIPPED =
  "No examples were fetched: many checks failed on this table, and the scan queries examples for the most severe ones only. The SQL lists the failing rows.";

/** Example values with their counts. Values arrive masked from the API where personal and
 * are rendered as text, never as HTML. `skipped`: the scan fetched none on purpose. */
export function Examples({ items, label = "Examples", skipped = false }: { items: ValueCount[]; label?: string; skipped?: boolean }) {
  if (items.length === 0) return skipped ? <p className="caption">{EXAMPLES_SKIPPED}</p> : null;
  return (
    <div className="examples">
      <p className="eyebrow">{label}</p>
      <ul>
        {items.map((ex, i) => (
          <li key={i}>
            {ex.value === null ? <span className="null-value">null</span> : <code className="value">{ex.value}</code>}
            <span className="num muted"> × {formatCount(ex.count)}</span>
            {ex.masked && <span className="muted text-sm"> (masked)</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
