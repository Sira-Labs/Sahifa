import { errorAdvice, errorReference } from "../api";

/** An API error with the server's message, what to do about it where the status says so
 * (spec 022), the reference to give the operator when the API itself failed (spec 023), and a
 * retry action. */
export function ErrorPanel({ title, error, onRetry }: { title: string; error: Error; onRetry?: () => void }) {
  const advice = errorAdvice(error);
  const reference = errorReference(error);
  return (
    <div role="alert" className="card error-panel">
      <p className="font-semibold">{title}</p>
      <p className="muted">{error.message}</p>
      {advice && <p className="text-sm">{advice}</p>}
      {reference && (
        <p className="text-sm">
          Reference: <code className="num">{reference}</code>. Whoever runs this install finds the error under it in the API&apos;s log.
        </p>
      )}
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
