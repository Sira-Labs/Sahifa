import { useState } from "react";
import { signOut } from "../auth";
import { PlainFrame } from "../components/Brand";

/** Signed in, but the address is neither the admin email nor an allowed one (403 `no_access`). */
export function NoAccess({ email }: { email: string | null }) {
  const [error, setError] = useState<string | null>(null);
  return (
    <PlainFrame>
      <section aria-labelledby="no-access-heading" className="stack">
        <h1 id="no-access-heading">No access yet</h1>
        <p>
          You are signed in{email ? <> as <strong className="break-anywhere">{email}</strong></> : null}, but this address has no
          access to this Sahifa yet.
        </p>
        <p className="muted">
          Ask its administrator to add your address to <code>SAHIFA_ALLOWED_EMAILS</code>, then sign in again. If you meant to use
          another account, sign out first.
        </p>
        <div>
          <button type="button" className="btn" onClick={() => signOut().catch((e: Error) => setError(e.message))}>
            Sign out
          </button>
        </div>
        {error && (
          <p role="alert" className="text-bad">
            Could not sign out: {error}
          </p>
        )}
      </section>
    </PlainFrame>
  );
}
