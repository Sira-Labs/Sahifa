import { formatCount } from "../format";
import type { ValueCount } from "../types";

/** Example values with their counts. Values arrive masked from the API where personal and
 * are rendered as text, never as HTML. */
export function Examples({ items, label = "Examples" }: { items: ValueCount[]; label?: string }) {
  if (items.length === 0) return null;
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
