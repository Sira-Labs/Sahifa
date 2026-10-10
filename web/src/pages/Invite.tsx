import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { signOut } from "../auth";
import { PlainFrame } from "../components/Brand";
import { formatLocalTime } from "../format";
import { forgetInvitation, keepInvitation, pendingInvitation } from "../invitation";
import { setWorkspaceFilter } from "../workspace";

/** The `detail` code of a failed request, if the API sent one. */
function codeOf(error: unknown): string | null {
  if (!(error instanceof ApiError) || !error.body || typeof error.body !== "object") return null;
  const detail = (error.body as { detail?: unknown }).detail;
  return typeof detail === "string" ? detail : null;
}

function Problem({ error }: { error: unknown }) {
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const code = codeOf(error);
  if (code === "invitation_used") {
    return (
      <div role="alert" className="stack-sm">
        <p>This invitation has been used already.</p>
        <p>
          <Link to="/">Go to Sahifa</Link>
        </p>
      </div>
    );
  }
  if (code === "invitation_invalid") {
    return (
      <p role="alert">
        This invitation link does not work any more: it has expired or an admin revoked it. Ask the person who invited you for a
        new link.
      </p>
    );
  }
  if (code === "invitation_other_email") {
    return (
      <div role="alert" className="stack-sm">
        <p>{error instanceof Error ? error.message : "This invitation is for another address."}</p>
        <div>
          <button type="button" className="btn" onClick={() => signOut().catch((e: Error) => setSignOutError(e.message))}>
            Sign out
          </button>
        </div>
        {signOutError && <p className="text-bad">Could not sign out: {signOutError}</p>}
      </div>
    );
  }
  if (error instanceof ApiError && error.status === 401) return <p role="status">Taking you to sign-in…</p>;
  return (
    <p role="alert" className="text-bad">
      {error instanceof Error ? error.message : "Something went wrong."}
    </p>
  );
}

/** `/invite` (spec 020): opens an invitation link, sends the person through sign-in if needed,
 * and accepts it. The token comes after `#` in the link and is kept in this tab only. */
export function Invite() {
  const location = useLocation();
  const navigate = useNavigate();
  const client = useQueryClient();
  const fromLink = location.hash || null;
  const [token] = useState(() => {
    if (fromLink) keepInvitation(fromLink);
    return fromLink ?? pendingInvitation();
  });
  // Drop the token from the address and the history: a sign-in redirect must not carry it.
  useEffect(() => {
    if (fromLink) void navigate({ to: "/invite", replace: true });
  }, [fromLink, navigate]);

  const lookup = useQuery({
    queryKey: ["invitation", token],
    queryFn: () => api.lookupInvitation(token ?? ""),
    enabled: token !== null,
    retry: false,
  });
  const accept = useMutation({
    mutationFn: () => api.acceptInvitation(token ?? ""),
    onSuccess: (done) => {
      forgetInvitation();
      setWorkspaceFilter(done.workspace.id);
      void client.invalidateQueries({ queryKey: ["me"] });
      void navigate({ to: "/" });
    },
  });

  return (
    <PlainFrame>
      <section aria-labelledby="invite-heading" className="stack">
        <div>
          <p className="eyebrow">Invitation</p>
          <h1 id="invite-heading">Join a workspace</h1>
        </div>
        {token === null && <p>This page opens an invitation link. Open the link you were sent; it ends with a long code.</p>}
        {lookup.isPending && token !== null && <p role="status">Checking the invitation…</p>}
        {lookup.isError && <Problem error={lookup.error} />}
        {lookup.isSuccess && (
          <>
            <p>
              {lookup.data.invited_by ?? "An admin"} invited you to <strong>{lookup.data.workspace.name}</strong> as{" "}
              <strong>{lookup.data.role}</strong>.
            </p>
            <p className="muted text-sm">
              For {lookup.data.email}. The link works until {formatLocalTime(lookup.data.expires_at)}.
            </p>
            <div>
              <button type="button" className="btn btn-primary" disabled={accept.isPending} onClick={() => accept.mutate()}>
                Accept and open the workspace
              </button>
            </div>
            {accept.isError && <Problem error={accept.error} />}
          </>
        )}
      </section>
    </PlainFrame>
  );
}
