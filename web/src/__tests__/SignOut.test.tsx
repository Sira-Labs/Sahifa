import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { browser } from "../auth";
import { DEV_ME, ME, renderApp, stubFetch } from "./helpers";

describe("Sign out", () => {
  it("shows the user, posts the logout with the CSRF header, then goes to the IdP's logout URL", async () => {
    const assign = vi.spyOn(browser, "assign").mockImplementation(() => {});
    const fetch = stubFetch(
      (url, init) => {
        if (url === "/api/auth/logout" && init?.method === "POST") return { logout_url: "https://idp.example/logout?id_token_hint=t" };
        if (url.startsWith("/api/scans")) return { items: [], next_cursor: null };
        throw new Error(`unexpected ${url}`);
      },
      { me: ME },
    );
    renderApp("/");

    expect(await screen.findByText(ME.user.display_name)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Account" }).getAttribute("href")).toBe("/settings/account");
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://idp.example/logout?id_token_hint=t"));
    const logout = fetch.mock.calls.find(([url, init]) => url === "/api/auth/logout" && init?.method === "POST");
    expect((logout?.[1]?.headers as Record<string, string>)["X-Sahifa-Request"]).toBe("1");
  });

  it("offers no sign-out behind the proxy's basic auth", async () => {
    stubFetch(() => ({ items: [], next_cursor: null }), {
      me: { ...DEV_ME, mode: "proxy", user: { id: null, email: null, display_name: "Basic auth" }, sign_in_method: "proxy" },
    });
    renderApp("/");
    await screen.findByRole("heading", { name: "No scans yet" });
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
  });
});
