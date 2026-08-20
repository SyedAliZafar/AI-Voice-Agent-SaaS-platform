/**
 * The signed-in workspace and user.
 *
 * These values are hardcoded on purpose: real auth (Clerk/Auth0 per CONTEXT.md's stack
 * table) is not built yet, and the dev auth token in `lib/api.ts` carries no profile.
 * Until it is, this module is the *single* place the UI invents an identity — previously
 * "Demo workspace", "Free plan" and the "AZ" avatar were retyped inline across Sidebar
 * and Topbar, so making them real meant hunting them down.
 *
 * When auth lands: replace the export with a hook reading the session and delete
 * nothing else.
 */
export interface Workspace {
  name: string;
  plan: string;
  user: { name: string; email: string };
}

export const workspace: Workspace = {
  name: "KrucX Automation",
  plan: "Growth plan",
  user: { name: "Alex Zafar", email: "alex@krucx.io" },
};

/** Two-letter avatar fallback: "Alex Zafar" -> "AZ", "KrucX" -> "KR". */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}
