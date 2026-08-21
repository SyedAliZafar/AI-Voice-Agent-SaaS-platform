"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ComponentType, SVGProps } from "react";

import {
  AgentsIcon,
  BrandMark,
  CallsIcon,
  ChevronRightIcon,
  DashboardIcon,
  LiveIcon,
  MicIcon,
  PhoneIcon,
  SettingsIcon,
  TargetIcon,
} from "@/components/icons";
import { initials, workspace } from "@/lib/workspace";

type NavItem = {
  href: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
};

/** Grouped rather than one flat list of seven: the sections name the job each page does,
 * so "where do I go to make it call someone" has an answer before you've learned the
 * vocabulary. Build comes first — creating an agent is the product's centre of gravity. */
type NavSection = { heading: string | null; items: NavItem[] };

const NAV: NavSection[] = [
  { heading: null, items: [{ href: "/dashboard", label: "Dashboard", icon: DashboardIcon }] },
  {
    heading: "Build",
    items: [
      { href: "/agents", label: "Agents", icon: AgentsIcon },
      { href: "/demo", label: "Demo", icon: MicIcon },
    ],
  },
  {
    heading: "Who to call",
    items: [
      { href: "/prospects", label: "Prospects", icon: TargetIcon },
      { href: "/leads", label: "Leads", icon: PhoneIcon },
    ],
  },
  {
    heading: "Monitor",
    items: [
      { href: "/calls", label: "Calls", icon: CallsIcon },
      { href: "/calls/live", label: "Live", icon: LiveIcon },
    ],
  },
  { heading: null, items: [{ href: "/settings", label: "Settings", icon: SettingsIcon }] },
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
      <Link href="/" className="flex h-16 items-center gap-2.5 px-5">
        <BrandMark />
        <span className="text-[15px] font-semibold tracking-tight text-slate-900">
          Voice<span className="text-brand-600">Agent</span>
        </span>
      </Link>

      <nav className="flex-1 px-3 py-2">
        {NAV.map((section, si) => (
          <div key={section.heading ?? `plain-${si}`} className={si === 0 ? "" : "mt-5"}>
            {section.heading && (
              <p className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                {section.heading}
              </p>
            )}
            <div className="space-y-1">
              {section.items.map(({ href, label, icon: Icon }) => {
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
                    <Icon
                      className={active ? "text-brand-600" : "text-slate-400"}
                      width={18}
                      height={18}
                    />
                    {label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="border-t border-slate-100 p-3">
        <Link
          href="/settings"
          className="flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-slate-50"
        >
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-100 text-sm font-semibold text-brand-700">
            {initials(workspace.name)}
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-900">{workspace.name}</p>
            <p className="truncate text-xs text-slate-500">{workspace.plan}</p>
          </div>
          <ChevronRightIcon width={16} height={16} className="ml-auto shrink-0 text-slate-300" />
        </Link>
      </div>
    </aside>
  );
}
