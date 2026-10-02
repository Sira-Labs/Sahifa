import { useQuery } from "@tanstack/react-query";
import { Link, Outlet } from "@tanstack/react-router";
import { useState } from "react";
import { ApiError, api } from "../api";
import { authApi, noAccessEmail, signOut } from "../auth";
import { BrandMark } from "../components/Brand";
import { ThemeToggle } from "../components/ThemeToggle";
import { NoAccess } from "./NoAccess";

const activeProps = { className: "is-active", "aria-current": "page" as const };

/** Page frame of the app: checks the session (spec 006), then the skip link, sticky header
 * with the mark, navigation, account and sign-out, the route, and the API version in the
 * footer. A 401 goes to /login (the API client's handler); an address without access sees
 * "No access yet". In dev and proxy mode `/api/auth/me` always answers, so nothing changes.
 * `children` replaces the route outlet (the not-found page of unknown paths). */
export function Layout({ children }: { children?: React.ReactNode }) {
  const me = useQuery({ queryKey: ["me"], queryFn: authApi.me, retry: false, staleTime: 60_000 });
  const version = useQuery({ queryKey: ["version"], queryFn: api.version, staleTime: 5 * 60_000, retry: false });
  const [signOutError, setSignOutError] = useState<string | null>(null);

  const denied = noAccessEmail(me.error);
  if (denied !== undefined) return <NoAccess email={denied} />;
  if (me.isPending || (me.error instanceof ApiError && me.error.status === 401)) {
    return (
      <p role="status" className="wrap main muted">
        Checking your session…
      </p>
    );
  }
  const signedIn = me.data?.mode === "oidc";

  return (
    <div className="app">
      <a href="#main" className="skip">
        Skip to content
      </a>
      <div className="topbar">
        <header className="wrap site-header">
          <Link to="/" className="brand" aria-label="Sahifa, scans">
            <BrandMark />
          </Link>
          <nav aria-label="Main" className="nav">
            <Link to="/" activeOptions={{ exact: true }} className="nav-link" activeProps={activeProps}>
              Scans
            </Link>
            <Link to="/scans/new" className="nav-link" activeProps={activeProps}>
              New scan
            </Link>
            <Link to="/connections" className="nav-link" activeProps={activeProps}>
              Connections
            </Link>
            {signedIn && (
              <>
                <Link to="/settings/account" className="nav-link" activeProps={activeProps}>
                  Account
                </Link>
                <span className="nav-user" title={me.data?.user.email ?? undefined}>
                  {me.data?.user.display_name}
                </span>
                <button type="button" className="btn btn-small btn-quiet" onClick={() => signOut().catch((e: Error) => setSignOutError(e.message))}>
                  Sign out
                </button>
              </>
            )}
            <ThemeToggle />
          </nav>
        </header>
      </div>
      <main id="main" className="wrap main" tabIndex={-1}>
        {signOutError && (
          <p role="alert" className="text-bad">
            Could not sign out: {signOutError}
          </p>
        )}
        {children ?? <Outlet />}
      </main>
      <footer className="wrap site-footer">
        <span>Sahifa · data quality with honest intervals</span>
        <span className="num">
          {version.isPending && "Connecting to the API…"}
          {version.isError && "API unreachable"}
          {version.data && `API ${version.data.version} · schema ${version.data.schema_revision}`}
        </span>
      </footer>
    </div>
  );
}
