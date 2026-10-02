import { useEffect, useRef, useState } from "react";

type CopyState = "idle" | "copied" | "failed";

/** The SQL that found a problem, collapsed by default, scrolling inside its own box, with a
 * copy button. */
export function SqlBlock({ sql, label = "SQL" }: { sql: string; label?: string }) {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  async function copy() {
    try {
      if (!navigator.clipboard) throw new Error("no clipboard");
      await navigator.clipboard.writeText(sql);
      setState("copied");
    } catch {
      setState("failed");
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2500);
  }

  return (
    <details className="sql-block">
      <summary>{label}</summary>
      <div className="sql-body">
        <div className="sql-tools">
          <button type="button" className="btn btn-small" onClick={copy}>
            Copy SQL
          </button>
          <span role="status" aria-live="polite" className="muted text-sm">
            {state === "copied" && "Copied"}
            {state === "failed" && "Copy failed: select the text instead"}
          </span>
        </div>
        <pre className="sql">
          <code>{sql}</code>
        </pre>
      </div>
    </details>
  );
}
