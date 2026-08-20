import Link from "next/link";

import { CheckIcon } from "@/components/icons";

const PLANS = [
  {
    name: "Starter",
    price: "$0",
    cadence: "to try it",
    blurb: "Wire up your Retell key and put one agent on the phone.",
    features: ["1 agent", "100 calls / month", "Text sandbox", "Call history & transcripts"],
    cta: "Start free",
    featured: false,
  },
  {
    name: "Growth",
    price: "$149",
    cadence: "/ month",
    blurb: "For teams running real outbound or inbound volume.",
    features: [
      "10 agents",
      "2,500 calls / month",
      "Live call monitoring",
      "Calendar & CRM actions",
      "Prospecting pipeline",
    ],
    cta: "Choose Growth",
    featured: true,
  },
  {
    name: "Scale",
    price: "Talk to us",
    cadence: "",
    blurb: "Higher concurrency, your own numbers, and hands-on onboarding.",
    features: [
      "Unlimited agents",
      "Volume call pricing",
      "Dedicated phone numbers",
      "Priority support",
    ],
    cta: "Get in touch",
    featured: false,
  },
];

export function Pricing() {
  return (
    <section id="pricing" className="border-t border-slate-200 bg-slate-50">
      <div className="mx-auto w-full max-w-6xl px-5 py-16 md:px-8 md:py-20">
        <h2 className="text-3xl font-semibold tracking-tight text-slate-900">
          Simple pricing
        </h2>
        <p className="mt-3 max-w-2xl text-slate-600">
          Bring your own Retell account — you pay them for telephony minutes, and us for
          everything wrapped around it.
        </p>

        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {PLANS.map((p) => (
            <div
              key={p.name}
              className={
                "flex flex-col rounded-2xl border bg-white p-6 " +
                (p.featured
                  ? "border-brand-300 shadow-card-hover ring-1 ring-brand-200"
                  : "border-slate-200 shadow-card")
              }
            >
              <div className="flex items-center justify-between">
                <h3 className="text-base font-semibold text-slate-900">{p.name}</h3>
                {p.featured && (
                  <span className="rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-medium text-brand-700">
                    Most popular
                  </span>
                )}
              </div>

              <div className="mt-4 flex items-baseline gap-1.5">
                <span className="text-3xl font-semibold tracking-tight text-slate-900">
                  {p.price}
                </span>
                {p.cadence && <span className="text-sm text-slate-500">{p.cadence}</span>}
              </div>

              <p className="mt-2 text-sm text-slate-600">{p.blurb}</p>

              <ul className="mt-5 flex-1 space-y-2.5">
                {p.features.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-sm text-slate-600">
                    <CheckIcon width={15} height={15} className="mt-0.5 shrink-0 text-emerald-500" />
                    {f}
                  </li>
                ))}
              </ul>

              <Link
                href="/dashboard"
                className={
                  "mt-6 rounded-xl px-4 py-2.5 text-center text-sm font-semibold transition-colors " +
                  (p.featured
                    ? "bg-brand-600 text-white hover:bg-brand-700"
                    : "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50")
                }
              >
                {p.cta}
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
