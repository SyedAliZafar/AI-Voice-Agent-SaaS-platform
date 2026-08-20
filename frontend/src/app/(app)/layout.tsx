import { ReactNode } from "react";

import { AppShell } from "@/components/layout/AppShell";

/** Every authenticated product route renders inside the app chrome. The `(app)` group
 * doesn't change any URL — /dashboard is still /dashboard — it just scopes this layout
 * so the marketing pages at `/` don't inherit a sidebar. */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="bg-slate-50">
      <AppShell>{children}</AppShell>
    </div>
  );
}
