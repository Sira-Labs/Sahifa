import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { pendingInvitation } from "../invitation";
import type { InvitationLookup } from "../types";
import { ME, json, renderApp, stubFetch } from "./helpers";

const TOKEN = "tok_0123456789abcdefghijklmnopqrstuvwxyzAB";
const LOOKUP: InvitationLookup = {
  workspace: { id: "w9", name: "Finance" },
  role: "editor",
  email: "n***@example.org",
  invited_by: "Ana",
  expires_at: "2026-10-17T08:00:00Z",
};

function body(init?: RequestInit): unknown {
  return init?.body ? JSON.parse(String(init.body)) : null;
}

beforeEach(() => sessionStorage.clear());

describe("/invite (spec 020)", () => {
  it("shows what the link does, accepts it and opens the workspace", async () => {
    const fetch = stubFetch(
      (url) => {
        if (url === "/api/invitations/lookup") return LOOKUP;
        if (url === "/api/invitations/accept") return { workspace: LOOKUP.workspace, role: "editor" };
        return { items: [], next_cursor: null };
      },
      { me: { ...ME, workspaces: [{ id: "w9", name: "Finance", role: "editor", is_default: false }] } },
    );
    const { router } = renderApp(`/invite#${TOKEN}`);
    expect(await screen.findByText(/Ana invited you to/)).toBeTruthy();
    expect(screen.getByText("Finance")).toBeTruthy();
    // The token left the address, and the lookup carried it in the body only.
    expect(router.state.location.href).not.toContain(TOKEN);
    const lookup = fetch.mock.calls.find(([url]) => url === "/api/invitations/lookup");
    expect(body(lookup?.[1])).toEqual({ token: TOKEN });
    await userEvent.setup().click(screen.getByRole("button", { name: "Accept and open the workspace" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
    const accept = fetch.mock.calls.find(([url]) => url === "/api/invitations/accept");
    expect(body(accept?.[1])).toEqual({ token: TOKEN });
    expect(pendingInvitation()).toBeNull();
  });

  it("sends a signed-out person to sign-in without the token in any URL, and keeps it for after", async () => {
    stubFetch((url) => (url === "/api/invitations/lookup" ? json({ detail: "not_authenticated" }, 401) : {}), {
      me: json({ detail: "not_authenticated" }, 401),
    });
    const { router } = renderApp(`/invite#${TOKEN}`);
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(router.state.location.href).not.toContain(TOKEN);
    expect(router.state.location.search).toEqual({ next: "/invite" });
    expect(await screen.findByText("Sign in to accept your invitation.")).toBeTruthy();
    expect(pendingInvitation()).toBe(TOKEN);
  });

  it.each([
    ["invitation_invalid", 404, /does not work any more/],
    ["invitation_used", 409, /has been used already/],
  ])("explains %s", async (detail, status, text) => {
    stubFetch(() => json({ detail, message: "x" }, status), { me: ME });
    renderApp(`/invite#${TOKEN}`);
    expect(await screen.findByText(text)).toBeTruthy();
  });

  it("asks a person signed in with another address to sign out", async () => {
    stubFetch(
      (url) =>
        url === "/api/invitations/lookup"
          ? LOOKUP
          : json(
              {
                detail: "invitation_other_email",
                email: "n***@example.org",
                message: "This invitation is for n***@example.org. Sign out and sign in with that address.",
              },
              403,
            ),
      { me: ME },
    );
    renderApp(`/invite#${TOKEN}`);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Accept and open the workspace" }));
    expect(await screen.findByText(/This invitation is for n\*\*\*@example.org/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
  });

  it("without a token, says to open the link", async () => {
    stubFetch(() => ({}), { me: ME });
    renderApp("/invite");
    expect(await screen.findByText(/Open the link you were sent/)).toBeTruthy();
  });

  it("offers the kept invitation on the no-access page", async () => {
    sessionStorage.setItem("sahifa.invitation", TOKEN);
    stubFetch(() => ({}), { me: json({ detail: "no_access", email: "new@example.org", message: "…" }, 403) });
    renderApp("/");
    const link = await screen.findByRole("link", { name: "Continue with your invitation" });
    expect(link.getAttribute("href")).toBe("/invite");
  });
});
