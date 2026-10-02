import { Link, createRootRoute, createRoute, createRouter, type RouterHistory } from "@tanstack/react-router";
import { AssetReport } from "./pages/AssetReport";
import { Connections } from "./pages/Connections";
import { Findings } from "./pages/Findings";
import { Layout } from "./pages/Layout";
import { NewScan } from "./pages/NewScan";
import { Report } from "./pages/Report";
import { ScansList } from "./pages/ScansList";
import { parseFindingFilters, parseNewScanSearch } from "./search";

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

const rootRoute = createRootRoute({ component: Layout, notFoundComponent: NotFound });

const scansRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: ScansList });

const newScanRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/scans/new",
  validateSearch: parseNewScanSearch,
  component: NewScan,
});

const reportRoute = createRoute({ getParentRoute: () => rootRoute, path: "/scans/$scanId", component: Report });

const assetRoute = createRoute({ getParentRoute: () => rootRoute, path: "/scans/$scanId/assets/$asset", component: AssetReport });

const findingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/scans/$scanId/findings",
  validateSearch: parseFindingFilters,
  component: Findings,
});

const connectionsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/connections", component: Connections });

export const routeTree = rootRoute.addChildren([
  scansRoute,
  newScanRoute,
  reportRoute,
  assetRoute,
  findingsRoute,
  connectionsRoute,
]);

/** The app router; tests pass a memory history. */
export function makeRouter(history?: RouterHistory) {
  return createRouter({ routeTree, history, defaultPreload: "intent", scrollRestoration: true });
}

export const router = makeRouter();

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
