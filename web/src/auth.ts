// Sign-in, the current user and devices (spec 006, ported from Tabayyun spec 013). The API is a
// backend-for-frontend: the browser holds only an HttpOnly session cookie, and sign-in and
// sign-out are full-page navigations through the identity provider.
import { ApiError, apiGet, apiSend } from "./api";

export type SignInMethod = "google" | "github" | "passkey";

/** `oidc`: sign-in required. `dev`: local, no sign-in. `proxy`: behind HTTP basic auth. */
export type AuthMode = "oidc" | "dev" | "proxy";

export type AuthOptions = {
  mode: AuthMode;
  methods: SignInMethod[];
  /** Keycloak's account console, where passkeys are managed; null without sign-in. */
  account_url: string | null;
};

export type Me = {
  mode: AuthMode;
  user: { id: string | null; email: string | null; display_name: string };
  /** `google`, `github`, `passkey`, or `dev` / `proxy` when the server runs without sign-in. */
  sign_in_method: string;
  admin: boolean;
};

export type Device = {
  id: string;
  current: boolean;
  sign_in_method: string;
  created_at: string;
  last_seen_at: string;
  user_agent: string | null;
  ip_address: string | null;
};

export const SIGN_IN_LABELS: Record<SignInMethod, string> = {
  google: "Continue with Google",
  github: "Continue with GitHub",
  passkey: "Sign in with a passkey",
};

export const METHOD_NAMES: Record<string, string> = {
  google: "Google",
  github: "GitHub",
  passkey: "a passkey",
  dev: "no sign-in (dev mode)",
  proxy: "the proxy's password (basic auth)",
};

/** `value` when it is a path on this site, else `/` (the server checks again). */
export function safeNext(value: string | undefined | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return "/";
  return value;
}

/** Where a sign-in button navigates. */
export function loginUrl(method: SignInMethod, next: string): string {
  return `/api/auth/login?${new URLSearchParams({ method, next: safeNext(next) })}`;
}

/** Page navigation, replaceable in tests (jsdom cannot navigate). */
export const browser = {
  assign(url: string): void {
    window.location.assign(url);
  },
};

export const authApi = {
  me: () => apiGet<Me>("/api/auth/me"),
  options: () => apiGet<AuthOptions>("/api/auth/options"),
  sessions: () => apiGet<Device[]>("/api/auth/sessions"),
  revokeSession: (id: string) => apiSend<void>("DELETE", `/api/auth/sessions/${encodeURIComponent(id)}`),
  revokeOthers: () => apiSend<void>("POST", "/api/auth/sessions/revoke-others"),
  logout: () => apiSend<{ logout_url: string }>("POST", "/api/auth/logout"),
};

/** Sign out here, then at the identity provider (which returns to the app). */
export async function signOut(): Promise<void> {
  const { logout_url } = await authApi.logout();
  browser.assign(logout_url);
}

/** The email a 403 `no_access` answer names: a string, null when it names none, undefined
 * when the error is something else. */
export function noAccessEmail(error: unknown): string | null | undefined {
  if (!(error instanceof ApiError) || error.status !== 403) return undefined;
  const body = error.body as { detail?: unknown; email?: unknown } | null;
  if (body?.detail !== "no_access") return undefined;
  return typeof body.email === "string" ? body.email : null;
}

/** A short name for a browser from its user agent, e.g. `Firefox on Windows`. */
export function deviceName(userAgent: string | null): string {
  if (!userAgent) return "Unknown device";
  const browserName = /Edg\//.test(userAgent)
    ? "Edge"
    : /Firefox\//.test(userAgent)
      ? "Firefox"
      : /Chrome\//.test(userAgent)
        ? "Chrome"
        : /Safari\//.test(userAgent)
          ? "Safari"
          : "Browser";
  const os = /iPhone|iPad/.test(userAgent)
    ? "iOS"
    : /Android/.test(userAgent)
      ? "Android"
      : /Windows/.test(userAgent)
        ? "Windows"
        : /Mac OS X/.test(userAgent)
          ? "macOS"
          : /Linux/.test(userAgent)
            ? "Linux"
            : null;
  return os ? `${browserName} on ${os}` : browserName;
}
