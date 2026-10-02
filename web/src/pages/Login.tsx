import { useQuery } from "@tanstack/react-query";
import { Link, useSearch } from "@tanstack/react-router";
import { SIGN_IN_LABELS, authApi, loginUrl, safeNext } from "../auth";
import { PlainFrame } from "../components/Brand";
import { ErrorPanel } from "../components/ErrorPanel";

/** `/login`: one button per enabled sign-in method; each is a navigation through the IdP. */
export function Login() {
  const { next } = useSearch({ from: "/login" });
  const options = useQuery({ queryKey: ["auth-options"], queryFn: authApi.options });
  const target = safeNext(next);
  const methods = options.data?.mode === "oidc" ? options.data.methods : [];

  return (
    <PlainFrame>
      <section aria-labelledby="login-heading" className="stack">
        <div>
          <p className="eyebrow">Welcome</p>
          <h1 id="login-heading">Sign in</h1>
        </div>
        {options.isPending && <p role="status">Loading sign-in options…</p>}
        {options.isError && (
          <ErrorPanel title="Could not reach the API" error={options.error} onRetry={() => void options.refetch()} />
        )}
        {methods.length > 0 && (
          <>
            <p className="muted">Sahifa has no passwords of its own. Sign in through Google, GitHub or a passkey you set up earlier.</p>
            <ul className="auth-methods">
              {methods.map((method) => (
                <li key={method}>
                  <a href={loginUrl(method, target)} className={method === "passkey" ? "btn" : "btn btn-primary"}>
                    {SIGN_IN_LABELS[method]}
                  </a>
                </li>
              ))}
            </ul>
          </>
        )}
        {options.isSuccess && methods.length === 0 && (
          <p className="muted">
            This server runs without sign-in{options.data.mode === "proxy" ? " (the proxy in front asks for a password)" : " (dev mode)"}.{" "}
            <Link to="/">Continue to the scans</Link>
          </p>
        )}
      </section>
    </PlainFrame>
  );
}
