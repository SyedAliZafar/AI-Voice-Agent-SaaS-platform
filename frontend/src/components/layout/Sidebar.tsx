"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ComponentType, SVGProps } from "react";

import {
  AgentsIcon,
  BrandMark,
  CallsIcon,
  DashboardIcon,
  LiveIcon,
  SettingsIcon,
  TargetIcon,
} from "@/components/icons";

type NavItem = {
  href: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
};

const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: DashboardIcon },
  { href: "/prospects", label: "Prospects", icon: TargetIcon },
  { href: "/agents", label: "Agents", icon: AgentsIcon },
  { href: "/calls", label: "Calls", icon: CallsIcon },
  { href: "/calls/live", label: "Live", icon: LiveIcon },
  { href: "/settings", label: "Settings", icon: SettingsIcon },
];

function isActive(pathname: string, href: string) {
  if (href === "/calls") {
    // Keep "Calls" from lighting up on the /calls/live route.
    return pathname === "/calls" || (pathname.startsWith("/calls/") && pathname !== "/calls/live");
  }
  return pathname === href || pathname.startsWith(href + "/");
}

export function Sidebar() {
  const pathname = usePathname() || "";

  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
      <div className="flex h-16 items-center gap-2.5 px-5">
        <BrandMark />
        <span className="text-[15px] font-semibold tracking-tight text-slate-900">
          Voice<span className="text-brand-600">Agent</span>
        </span>
      </div>

      <nav className="flex-1 space-y-1 px-3 py-2">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              className={
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors " +
                (active
                  ? "bg-brand-50 text-brand-700"
                  : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")
              }
            >
              <Icon className={active ? "text-brand-600" : "text-slate-400"} width={18} height={18} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-slate-100 p-3">
        <div className="flex items-center gap-3 rounded-lg px-2 py-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-100 text-sm font-semibold text-brand-700">
            AZ
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-900">Demo workspace</p>
            <p className="truncate text-xs text-slate-500">Free plan</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
