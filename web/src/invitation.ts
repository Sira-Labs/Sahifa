// The token of an invitation link (spec 020) between opening the link and accepting it. The link
// carries it after `#`; `/invite` moves it to sessionStorage and drops it from the address, so
// the round trip through sign-in never puts it in a URL the server sees.
const KEY = "sahifa.invitation";

/** Keep the token for this tab; storage can be unavailable (private mode), which only costs the
 * convenience of coming back to it after sign-in. */
export function keepInvitation(token: string): void {
  try {
    sessionStorage.setItem(KEY, token);
  } catch {
    // Without storage the person opens the link again after signing in.
  }
}

export function pendingInvitation(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function forgetInvitation(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // Nothing kept, nothing to forget.
  }
}
