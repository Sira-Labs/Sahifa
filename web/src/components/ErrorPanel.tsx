/** An API error with the server's message and a retry action. */
export function ErrorPanel({ title, error, onRetry }: { title: string; error: Error; onRetry?: () => void }) {
  return (
    <div role="alert" className="card error-panel">
      <p className="font-semibold">{title}</p>
      <p className="muted">{error.message}</p>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
