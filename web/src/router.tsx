import { Link, Outlet, createRootRoute, createRoute, createRouter, type RouterHistory } from "@tanstack/react-router";
import { setUnauthorizedHandler } from "./api";
import { Account } from "./pages/Account";
import { isPasskeyStatus, type PasskeyStatus } from "./auth";
import { AssetReport } from "./pages/AssetReport";
import { Connections } from "./pages/Connections";
import { Findings } from "./pages/Findings";
import { FindingPage, FindingsAcross } from "./pages/FindingsAcross";
import { Layout } from "./pages/Layout";
import { Login } from "./pages/Login";
import { NewScan } from "./pages/NewScan";
import { Report } from "./pages/Report";
import { ScansList } from "./pages/ScansList";
import { parseFindingFilters, parseFindingsSearch, parseNewScanSearch } from "./search";

/** Fallback for unknown paths. */
function NotFound() {
  return (
    <div className="card stack-sm">
      <h1>Page not found</h1>
      <p>
        <Link to="/">Back to the scans</Link>
      </p>
    </div>
  );
}

// Unknown paths match no layout route, so the root draws the frame around the not-found page.
const rootRoute = createRootRoute({
  component: Outlet,
  notFoundComponent: () => (
    <Layout>
      <NotFound />
    </Layout>
  ),
});

// Everything but /login lives under the app layout, which checks the session (spec 006).
const appRoute = createRoute({ getParentRoute: () => rootRoute, id: "_app", component: Layout, notFoundComponent: NotFound });

const scansRoute = createRoute({ getParentRoute: () => appRoute, path: "/", component: ScansList });

const newScanRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/scans/new",
  validateSearch: parseNewScanSearch,
  component: NewScan,
});

const reportRoute = createRoute({ getParentRoute: () => appRoute, path: "/scans/$scanId", component: Report });

const assetRoute = createRoute({ getParentRoute: () => appRoute, path: "/scans/$scanId/assets/$asset", component: AssetReport });

const findingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/scans/$scanId/findings",
  validateSearch: parseFindingFilters,
  component: Findings,
});

// Findings across scans (spec 009).
const findingsAcrossRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/findings",
  validateSearch: parseFindingsSearch,
  component: FindingsAcross,
});

const findingRoute = createRoute({ getParentRoute: () => appRoute, path: "/findings/$findingId", component: FindingPage });

const connectionsRoute = createRoute({ getParentRoute: () => appRoute, path: "/connections", component: Connections });

const accountRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/settings/account",
  validateSearch: (search: Record<string, unknown>): { passkey?: PasskeyStatus } =>
    isPasskeyStatus(search.passkey) ? { passkey: search.passkey } : {},
  component: Account,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: (search: Record<string, unknown>): { next?: string } =>
    typeof search.next === "string" ? { next: search.next } : {},
  component: Login,
});

export const routeTree = rootRoute.addChildren([
  appRoute.addChildren([
    scansRoute,
    newScanRoute,
    reportRoute,
    assetRoute,
    findingsRoute,
    findingsAcrossRoute,
    findingRoute,
    connectionsRoute,
    accountRoute,
  ]),
  loginRoute,
]);

/** The app router; tests pass a memory history. A 401 from any API call goes to /login with
 * the current path as `next`. */
export function makeRouter(history?: RouterHistory) {
  const router = createRouter({ routeTree, history, defaultPreload: "intent", scrollRestoration: true });
  setUnauthorizedHandler(() => {
    const { pathname, href } = router.state.location;
    if (pathname !== "/login") void router.navigate({ to: "/login", search: { next: href } });
  });
  return router;
}

export const router = makeRouter();

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
