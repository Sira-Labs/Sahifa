import { errorAdvice } from "../api";

/** An API error with the server's message, what to do about it where the status says so
 * (spec 022), and a retry action. */
export function ErrorPanel({ title, error, onRetry }: { title: string; error: Error; onRetry?: () => void }) {
  const advice = errorAdvice(error);
  return (
    <div role="alert" className="card error-panel">
      <p className="font-semibold">{title}</p>
      <p className="muted">{error.message}</p>
      {advice && <p className="text-sm">{advice}</p>}
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
