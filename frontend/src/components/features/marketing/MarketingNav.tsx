import Link from "next/link";

import { BrandMark } from "@/components/icons";

const LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#features", label: "Features" },
  { href: "#pricing", label: "Pricing" },
];

export function MarketingNav() {
  return (
    <header className="sticky top-0 z-20 border-b border-slate-200/70 bg-white/80 backdrop-blur">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-5 md:px-8">
        <Link href="/" className="flex items-center gap-2.5">
          <BrandMark />
          <span className="text-[15px] font-semibold tracking-tight text-slate-900">
            Voice<span className="text-brand-600">Agent</span>
          </span>
        </Link>

        <nav className="hidden items-center gap-7 md:flex">
          {LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="text-sm font-medium text-slate-600 transition-colors hover:text-slate-900"
            >
              {l.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <Link
            href="/dashboard"
            className="hidden rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:text-slate-900 sm:block"
          >
            Log in
          </Link>
          <Link
            href="/dashboard"
            className="rounded-lg bg-slate-900 px-3.5 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-slate-800"
          >
            Open dashboard
          </Link>
        </div>
      </div>
    </header>
  );
}
