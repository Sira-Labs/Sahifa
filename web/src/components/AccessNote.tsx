import { useState } from "react";
import type { SourceAccess } from "../types";

/** "3 tables", "1 table". */
function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** What makes a login able to write, as one short line. */
function writeReasons(access: SourceAccess): string {
  const parts: string[] = [];
  if (access.writable_count) parts.push(`may change ${count(access.writable_count, "table or file", "tables or files")}`);
  if (access.can_create_in.length) parts.push(`may create in ${access.can_create_in.join(", ")}`);
  if (access.role_flags.length) parts.push(access.role_flags.join(", "));
  return parts.join("; ");
}

/** The access verdict under a connection's Test button (spec 021). */
export function AccessResult({ access }: { access: SourceAccess }) {
  const [open, setOpen] = useState(false);
  if (access.verdict === "read_only") {
    return <span className="text-ok">✓ Read-only login</span>;
  }
  if (access.verdict === "unknown") {
    return <span className="muted">Could not tell what this login may do{access.reason ? `: ${access.reason}` : ""}.</span>;
  }
  const more = access.writable_count - access.writable.length;
  return (
    <span className="stack-xs access-result">
      <span className="text-warn font-semibold">This login could write: {writeReasons(access)}.</span>
      {access.advice && <span className="text-sm">{access.advice}</span>}
      {access.writable.length > 0 && (
        <>
          <button type="button" className="btn btn-small btn-quiet" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "Hide" : "Show"} what it could change
          </button>
          {open && (
            <ul className="plain-list text-sm break-anywhere" aria-label="Writable tables or files">
              {access.writable.map((name) => (
                <li key={name}>{name}</li>
              ))}
              {more > 0 && <li className="muted">and {more} more</li>}
            </ul>
          )}
        </>
      )}
    </span>
  );
}

/** A warning above a report whose scan ran with a login that could write (spec 021). */
export function AccessWarning({ access }: { access: SourceAccess | null | undefined }) {
  if (access?.verdict !== "can_write") return null;
  return (
    <aside className="callout callout-warn stack-xs" aria-label="Login rights">
      <p className="font-semibold">The login this scan used could write to the source.</p>
      <p>
        Sahifa only reads ({writeReasons(access)}), but a read-only login is the safer guarantee.{" "}
        {access.advice}
      </p>
    </aside>
  );
}
