import Link from "next/link";

import { BrandMark } from "@/components/icons";

export function MarketingFooter() {
  return (
    <>
      {/* Closing call to action */}
      <section className="border-t border-slate-200 bg-white">
        <div className="mx-auto w-full max-w-6xl px-5 py-16 md:px-8 md:py-20">
          <div className="overflow-hidden rounded-3xl bg-slate-900 px-8 py-12 text-center md:px-16 md:py-16">
            <h2 className="text-3xl font-semibold tracking-tight text-white">
              Your first agent is ten minutes away
            </h2>
            <p className="mx-auto mt-3 max-w-xl text-slate-400">
              Paste in a Retell key, answer a few questions, and hear it talk.
            </p>
            <Link
              href="/agents/new"
              className="mt-8 inline-block rounded-xl bg-white px-6 py-3 text-sm font-semibold text-slate-900 transition-colors hover:bg-slate-100"
            >
              Build an agent
            </Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-5 py-8 md:flex-row md:items-center md:justify-between md:px-8">
          <div className="flex items-center gap-2.5">
            <BrandMark width={22} height={22} />
            <span className="text-sm font-semibold tracking-tight text-slate-900">
              Voice<span className="text-brand-600">Agent</span>
            </span>
          </div>

          <nav className="flex flex-wrap gap-x-6 gap-y-2">
            {[
              { href: "#how", label: "How it works" },
              { href: "#features", label: "Features" },
              { href: "#pricing", label: "Pricing" },
              { href: "/dashboard", label: "Dashboard" },
            ].map((l) => (
              <a
                key={l.label}
                href={l.href}
                className="text-sm text-slate-500 transition-colors hover:text-slate-900"
              >
                {l.label}
              </a>
            ))}
          </nav>

          <p className="text-sm text-slate-400">
            © {new Date().getFullYear()} VoiceAgent
          </p>
        </div>
      </footer>
    </>
  );
}
