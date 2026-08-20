import Link from "next/link";

import { CheckIcon, PhoneIcon } from "@/components/icons";

/** A stylised rendering of the live-call view — not a screenshot, so it can't go stale
 * when the real page changes. The transcript below is taken from the HVAC/Solar
 * template's opening sequence (scripts/agent_templates), so the pitch it shows is one
 * the product can actually deliver. */
function CallPreview() {
  const turns = [
    { who: "agent", text: "Hi, it’s Ava calling from KrucX — did I catch you mid-job?" },
    { who: "caller", text: "Uh, sort of. What’s this about?" },
    { who: "agent", text: "Quick one. When a no-heat call comes in after hours, where does it go right now?" },
    { who: "caller", text: "Voicemail, mostly. We call back next morning." },
  ];

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900 p-1.5 shadow-2xl shadow-slate-900/25">
      <div className="rounded-xl bg-slate-950/60 ring-1 ring-white/5">
        {/* window chrome */}
        <div className="flex items-center gap-2 border-b border-white/5 px-4 py-3">
          <span className="h-2.5 w-2.5 rounded-full bg-slate-700" />
          <span className="h-2.5 w-2.5 rounded-full bg-slate-700" />
          <span className="h-2.5 w-2.5 rounded-full bg-slate-700" />
          <span className="ml-2 font-mono text-[11px] text-slate-500">live call</span>
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
            Connected · 01:12
          </span>
        </div>

        {/* agent identity */}
        <div className="flex items-center gap-3 border-b border-white/5 px-4 py-3.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-500/15 text-brand-300">
            <PhoneIcon width={16} height={16} />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-100">HVAC · Outbound qualifier</p>
            <p className="truncate font-mono text-[11px] text-slate-500">retell · +1 (415) 555-0142</p>
          </div>
          <div className="ml-auto flex items-end gap-[3px]" aria-hidden>
            {[10, 18, 8, 22, 14, 6, 16].map((h, i) => (
              <span key={i} className="w-[3px] rounded-full bg-brand-400/70" style={{ height: h }} />
            ))}
          </div>
        </div>

        {/* transcript */}
        <div className="space-y-2.5 px-4 py-4">
          {turns.map((t, i) => (
            <div key={i} className={t.who === "agent" ? "flex" : "flex justify-end"}>
              <p
                className={
                  "max-w-[85%] rounded-2xl px-3 py-2 text-[13px] leading-relaxed " +
                  (t.who === "agent"
                    ? "rounded-tl-sm bg-brand-500/15 text-brand-50"
                    : "rounded-tr-sm bg-white/5 text-slate-300")
                }
              >
                {t.text}
              </p>
            </div>
          ))}
          <div className="flex">
            <span className="rounded-2xl rounded-tl-sm bg-brand-500/15 px-3 py-2.5">
              <span className="flex gap-1" aria-label="agent is speaking">
                {[0, 150, 300].map((d) => (
                  <span
                    key={d}
                    className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-300"
                    style={{ animationDelay: `${d}ms` }}
                  />
                ))}
              </span>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Hero() {
  return (
    <section className="relative overflow-hidden bg-white">
      {/* soft brand wash behind the hero */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-40 h-[520px] bg-[radial-gradient(60%_60%_at_50%_40%,rgba(99,102,241,0.14),transparent_70%)]"
      />

      <div className="relative mx-auto grid w-full max-w-6xl gap-14 px-5 py-16 md:px-8 md:py-24 lg:grid-cols-2 lg:items-center">
        <div>
          <span className="inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700">
            <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
            Connected to your Retell account
          </span>

          <h1 className="mt-5 text-4xl font-semibold leading-[1.1] tracking-tight text-slate-900 md:text-5xl">
            Build a voice agent.
            <br />
            Put it on a real phone line.
          </h1>

          <p className="mt-5 max-w-xl text-lg leading-relaxed text-slate-600">
            Describe the agent you want, and VoiceAgent writes the script, wires it to Retell,
            and dials. Watch the transcript live, listen back, and tune the prompt — without
            leaving the dashboard.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/agents/new"
              className="rounded-xl bg-brand-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-700"
            >
              Build an agent
            </Link>
            <Link
              href="/dashboard"
              className="rounded-xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:bg-slate-50"
            >
              Open the dashboard
            </Link>
          </div>

          <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2">
            {[
              "Bring your own Retell key",
              "Live transcript + barge-in",
              "Test by text before you dial",
            ].map((f) => (
              <li key={f} className="flex items-center gap-1.5 text-sm text-slate-500">
                <CheckIcon width={15} height={15} className="text-emerald-500" />
                {f}
              </li>
            ))}
          </ul>
        </div>

        <CallPreview />
      </div>
    </section>
  );
}
