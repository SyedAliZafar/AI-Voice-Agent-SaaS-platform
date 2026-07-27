"use client";

import { usePathname } from "next/navigation";

import { BrandMark } from "@/components/icons";

const TITLES: { match: (p: string) => boolean; label: string }[] = [
  { match: (p) => p === "/dashboard", label: "Dashboard" },
  { match: (p) => p === "/prospects", label: "Prospects" },
  { match: (p) => p === "/agents", label: "Agents" },
  { match: (p) => p === "/agents/new", label: "New agent" },
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
        <span className="md:hidden">
          <BrandMark width={26} height={26} />
        </span>
        <span className="text-sm font-medium text-slate-500">{current}</span>
      </div>

      <div className="flex items-center gap-3">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Demo tenant
        </span>
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">
          AZ
        </div>
      </div>
    </header>
  );
}
