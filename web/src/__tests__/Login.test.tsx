import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DEV_ME, json, renderApp, stubFetch } from "./helpers";

const OIDC = { mode: "oidc", methods: ["google", "github", "passkey"], account_url: "https://kc.example/realms/sahifa/account" };

describe("Login", () => {
  it("shows one button per configured sign-in method, each carrying next", async () => {
    stubFetch((url) => {
      if (url === "/api/auth/options") return { ...OIDC, methods: ["google", "passkey"] };
      throw new Error(`unexpected ${url}`);
    });
    renderApp("/login?next=%2Fscans%2Fabc");

    const google = await screen.findByRole("link", { name: "Continue with Google" });
    expect(google.getAttribute("href")).toBe("/api/auth/login?method=google&next=%2Fscans%2Fabc");
    expect(screen.getByRole("link", { name: "Sign in with a passkey" }).getAttribute("href")).toBe(
      "/api/auth/login?method=passkey&next=%2Fscans%2Fabc",
    );
    expect(screen.queryByRole("link", { name: "Continue with GitHub" })).toBeNull();
  });

  it("drops a next that leaves the site", async () => {
    stubFetch(() => OIDC);
    renderApp("/login?next=%2F%2Fevil.example");
    const github = await screen.findByRole("link", { name: "Continue with GitHub" });
    expect(github.getAttribute("href")).toBe("/api/auth/login?method=github&next=%2F");
  });

  it("sends a signed-out user to /login with the current path", async () => {
    stubFetch(
      (url) => {
        if (url === "/api/auth/options") return OIDC;
        return json({ detail: "not_authenticated" }, 401);
      },
      { me: json({ detail: "not_authenticated" }, 401) },
    );
    const { router } = renderApp("/connections?x=1");

    await screen.findByRole("heading", { name: "Sign in" });
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(router.state.location.search).toEqual({ next: "/connections?x=1" });
    expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
  });

  it("explains a server without sign-in, and the app needs none", async () => {
    stubFetch((url) => {
      if (url === "/api/auth/options") return { mode: "dev", methods: [], account_url: null };
      if (url.startsWith("/api/scans")) return { items: [], next_cursor: null };
      throw new Error(`unexpected ${url}`);
    });
    renderApp("/login");
    expect(await screen.findByText(/runs without sign-in/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Continue with/ })).toBeNull();
  });

  it("dev mode opens the app directly, without account or sign-out", async () => {
    stubFetch(() => ({ items: [], next_cursor: null }), { me: DEV_ME });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "No scans yet" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Account" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
  });
});

describe("Unknown paths", () => {
  it("show the not-found page inside the app frame", async () => {
    stubFetch((url) => {
      throw new Error(`unexpected ${url}`);
    });
    renderApp("/no/such/page");
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeTruthy();
  });
});
