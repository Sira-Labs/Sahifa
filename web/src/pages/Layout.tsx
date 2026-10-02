import { useQuery } from "@tanstack/react-query";
import { Link, Outlet } from "@tanstack/react-router";
import { api } from "../api";
import { ThemeToggle } from "../components/ThemeToggle";

/** Page frame: skip link, sticky header with the mark, navigation and theme toggle, the route,
 * and the API version in the footer. */
export function Layout() {
  const version = useQuery({ queryKey: ["version"], queryFn: api.version, staleTime: 5 * 60_000, retry: false });

  return (
    <div className="app">
      <a href="#main" className="skip">
        Skip to content
      </a>
      <div className="topbar">
        <header className="wrap site-header">
          <Link to="/" className="brand" aria-label="Sahifa, scans">
            <img src="/logo.svg" alt="" width="34" height="34" className="brand-mark" />
            <span>Sahifa</span>
            <span className="brand-ar" lang="ar" dir="rtl" aria-hidden="true">
              صحيفة
            </span>
          </Link>
          <nav aria-label="Main" className="nav">
            <Link to="/" activeOptions={{ exact: true }} className="nav-link" activeProps={{ className: "is-active", "aria-current": "page" }}>
              Scans
            </Link>
            <Link to="/scans/new" className="nav-link" activeProps={{ className: "is-active", "aria-current": "page" }}>
              New scan
            </Link>
            <Link to="/connections" className="nav-link" activeProps={{ className: "is-active", "aria-current": "page" }}>
              Connections
            </Link>
            <ThemeToggle />
          </nav>
        </header>
      </div>
      <main id="main" className="wrap main" tabIndex={-1}>
        <Outlet />
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
