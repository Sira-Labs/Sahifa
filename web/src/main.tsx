import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
// Self-hosted fonts: bundled into the image, no request to Google from the app.
import "@fontsource/bricolage-grotesque/500.css";
import "@fontsource/bricolage-grotesque/700.css";
import "@fontsource/figtree/400.css";
import "@fontsource/figtree/500.css";
import "@fontsource/figtree/600.css";
import "@fontsource/figtree/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/noto-kufi-arabic/500.css";
import "@fontsource/noto-kufi-arabic/700.css";
import { ApiError } from "./api";
import { router } from "./router";
import { applyStoredTheme } from "./theme";
import "./index.css";

applyStoredTheme();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      // Retry once on network and server errors; a 4xx answer is final.
      retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
