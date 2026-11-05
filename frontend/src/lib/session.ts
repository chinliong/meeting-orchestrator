// Browser-persisted session state: the logged-in account, and (for guests) the boards
// they hold share links to. Guests have no server-side account, so their list of reachable
// workspaces lives here — losing it means losing access unless they saved the links.

import type { AuthResponse, Project, User } from "./types";

const AUTH_KEY = "mo.auth";
const MODE_KEY = "mo.mode"; // "guest" once a guest session is chosen
const GUEST_WS_KEY = "mo.guestWorkspaces";

// Storage can be unavailable (site data blocked, some private windows) or full, and then every
// access throws. The app still works for that visit, it just remembers nothing.
function read<T>(key: string): T | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* not saved; see above */
  }
}

function remove(key: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* nothing stored to remove */
  }
}

// --- account ---
export const loadAuth = () => read<AuthResponse>(AUTH_KEY);
export const saveAuth = (auth: AuthResponse) => write(AUTH_KEY, auth);
export const clearAuth = () => remove(AUTH_KEY);

/** Refresh just the user portion of stored auth (e.g. after changing notification settings). */
export function updateStoredUser(user: User) {
  const stored = loadAuth();
  if (stored) write(AUTH_KEY, { ...stored, user });
}

// --- guest mode flag ---
export const isGuestChosen = () => read<string>(MODE_KEY) === "guest";
export const setGuestChosen = () => write(MODE_KEY, "guest");
export const clearGuestChosen = () => remove(MODE_KEY);

// --- guest's reachable boards ---
export const loadGuestWorkspaces = (): Project[] => read<Project[]>(GUEST_WS_KEY) ?? [];

export function saveGuestWorkspaces(projects: Project[]) {
  write(GUEST_WS_KEY, projects);
}

/** Add or update a board in the guest's list (de-duped by id). Most recent first. */
export function upsertGuestWorkspace(project: Project): Project[] {
  const rest = loadGuestWorkspaces().filter((p) => p.id !== project.id);
  const next = [project, ...rest];
  saveGuestWorkspaces(next);
  return next;
}

export function removeGuestWorkspace(id: number): Project[] {
  const next = loadGuestWorkspaces().filter((p) => p.id !== id);
  saveGuestWorkspaces(next);
  return next;
}

export const clearGuestWorkspaces = () => remove(GUEST_WS_KEY);

// --- boards other people shared with a signed-in user ---
// A signed-in user's own boards come from the server, but a board someone shared with them is
// reached only through its link. The links they have opened are remembered here, per account,
// and reopened on each visit, as a guest's boards are; a link that stops working is dropped.
interface SharedBoardLink {
  id: number;
  token: string;
}
const sharedKey = (userId: number) => `mo.sharedBoards.${userId}`;

export const loadSharedBoards = (userId: number): SharedBoardLink[] => read<SharedBoardLink[]>(sharedKey(userId)) ?? [];

/** Remember the link a board was opened with (most recent first, one entry per board). */
export function rememberSharedBoard(userId: number, id: number, token: string) {
  write(sharedKey(userId), [{ id, token }, ...loadSharedBoards(userId).filter((b) => b.id !== id)]);
}

export function forgetSharedBoard(userId: number, id: number) {
  write(sharedKey(userId), loadSharedBoards(userId).filter((b) => b.id !== id));
}

/** The token used as X-Workspace-Token for a board: edit token if held, else view token. */
export const workspaceTokenFor = (p: Project): string => p.edit_token ?? p.view_token;
