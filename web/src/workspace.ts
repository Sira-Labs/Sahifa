// Workspaces and roles in the web app (spec 016): the caller's workspaces from `/api/auth/me`,
// the header's workspace filter (stored per browser) and what a role may change. The API
// enforces every rule; the app only disables what it would refuse, and says why.
import { useQuery } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import { authApi, type Me, type MeWorkspace } from "./auth";
import type { WorkspaceRole } from "./types";

export const VIEWER_REASON = "Viewers can look but not change. Ask a workspace admin for the editor role.";

const RANK: Record<WorkspaceRole, number> = { viewer: 1, editor: 2, admin: 3 };

/** Whether `role` is at least `needs`. An object without a role (an API before spec 016) is
 * not restricted here; the API decides. */
export function allows(role: WorkspaceRole | null | undefined, needs: WorkspaceRole = "editor"): boolean {
  return role == null || RANK[role] >= RANK[needs];
}

/** The signed-in person, shared with the layout's session check. */
export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: authApi.me, retry: false, staleTime: 60_000 });
}

/** Workspaces where the person may change things (editor or admin). */
export function editableWorkspaces(me: Me | undefined): MeWorkspace[] {
  return (me?.workspaces ?? []).filter((w) => allows(w.role));
}

/** Whether the person administers any workspace, or is the org admin: who sees /workspaces. */
export function administers(me: Me | undefined): boolean {
  return !!me && (me.org_admin || me.workspaces.some((w) => w.role === "admin"));
}

// The header's choice, kept in localStorage and shared by every list through this store.
const KEY = "sahifa.workspace";
const listeners = new Set<() => void>();

function read(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

let chosen: string | null = read();

export function setWorkspaceFilter(id: string | null): void {
  chosen = id;
  try {
    if (id) window.localStorage.setItem(KEY, id);
    else window.localStorage.removeItem(KEY);
  } catch {
    // Storage blocked: the choice lasts until the page reloads.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The workspace the lists are filtered to, or undefined for all. Only a workspace the person
 * still sees, and only when they see more than one. */
export function useWorkspaceFilter(): string | undefined {
  const me = useMe();
  const value = useSyncExternalStore(subscribe, () => chosen);
  const workspaces = me.data?.workspaces ?? [];
  if (workspaces.length < 2 || !value) return undefined;
  return workspaces.some((w) => w.id === value) ? value : undefined;
}

/** Whether lists should name each item's workspace: the person sees more than one. */
export function useShowsWorkspaces(): boolean {
  return (useMe().data?.workspaces.length ?? 0) > 1;
}
