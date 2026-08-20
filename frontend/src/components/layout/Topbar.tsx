"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { BrandMark, PlusIcon } from "@/components/icons";
import { initials, workspace } from "@/lib/workspace";

const TITLES: { match: (p: string) => boolean; label: string }[] = [
  { match: (p) => p === "/dashboard", label: "Dashboard" },
  { match: (p) => p === "/prospects", label: "Prospects" },
  { match: (p) => p.startsWith("/prospects/"), label: "Prospect sandbox" },
  { match: (p) => p === "/leads", label: "Leads" },
  { match: (p) => p === "/agents", label: "Agents" },
  { match: (p) => p === "/agents/new", label: "New agent" },
  { match: (p) => p.endsWith("/sandbox"), label: "Agent sandbox" },
  { match: (p) => p.startsWith("/agents/"), label: "Agent" },
  { match: (p) => p === "/calls/live", label: "Live monitor" },
  { match: (p) => p === "/calls", label: "Calls" },
  { match: (p) => p.startsWith("/calls/"), label: "Call detail" },
  { match: (p) => p === "/settings", label: "Settings" },
];

export function Topbar() {
  const pathname = usePathname() || "";
  const current = TITLES.find((t) => t.match(pathname))?.label ?? "";

  return (
    <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-slate-200 bg-white/80 px-4 backdrop-blur md:px-8">
      <div className="flex items-center gap-2.5">
        {/* Brand shows on mobile where the sidebar is hidden */}
        <Link href="/dashboard" className="md:hidden">
          <BrandMark width={26} height={26} />
        </Link>
        <span className="text-sm font-medium text-slate-500">{current}</span>
      </div>

      <div className="flex items-center gap-3">
        <Link
          href="/agents/new"
          className="hidden items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 sm:inline-flex"
        >
          <PlusIcon width={14} height={14} />
          New agent
        </Link>

        <Link
          href="/settings"
          className="flex items-center gap-2.5"
          title={`${workspace.user.name} · ${workspace.user.email}`}
        >
          <div className="hidden text-right leading-tight lg:block">
            <p className="text-sm font-medium text-slate-900">{workspace.user.name}</p>
            <p className="text-xs text-slate-500">{workspace.name}</p>
          </div>
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">
            {initials(workspace.user.name)}
          </div>
        </Link>
      </div>
    </header>
  );
}
