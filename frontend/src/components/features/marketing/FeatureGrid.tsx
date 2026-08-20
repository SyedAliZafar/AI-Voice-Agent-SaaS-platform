import { ComponentType, SVGProps } from "react";

import {
  AgentsIcon,
  CheckIcon,
  ClockIcon,
  LiveIcon,
  RefreshIcon,
  SparkleIcon,
  TargetIcon,
} from "@/components/icons";

type Feature = {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  title: string;
  body: string;
};

/** Every card here maps to something that actually exists in the product — the ADRs in
 * CONTEXT.md are the source. Don't add aspirational rows; a demo that can't back up a
 * claim on screen is worse than a shorter list. */
const FEATURES: Feature[] = [
  {
    icon: LiveIcon,
    title: "Watch calls as they happen",
    body: "Transcripts stream into the dashboard turn by turn over a websocket, so you can follow a live call instead of reading it back an hour later.",
  },
  {
    icon: SparkleIcon,
    title: "Interruptions that feel human",
    body: "Talk over the agent and it stops — but a “mhm” in the first second doesn’t shred its sentence. Backchannel gets absorbed; a real objection cuts in immediately.",
  },
  {
    icon: CheckIcon,
    title: "It can actually do things",
    body: "Book, reschedule, or cancel on a real calendar mid-call, and push the contact to your CRM. Tools run on our server, so every invocation is logged and guarded.",
  },
  {
    icon: AgentsIcon,
    title: "Agents you built in Retell",
    body: "Already have agents in the Retell dashboard? They show up here live and you can dial them straight from the list — prompt, voice and brain stay theirs.",
  },
  {
    icon: RefreshIcon,
    title: "Nothing falls through",
    body: "If a webhook goes missing, the platform is asked directly for the real outcome. A call never gets stranded halfway with no duration and no transcript.",
  },
  {
    icon: TargetIcon,
    title: "Know who to call",
    body: "Search a city and a trade, and the pipeline finds the businesses, researches each one, and writes a script personalised to them before the phone rings.",
  },
];

export function FeatureGrid() {
  return (
    <section id="features" className="border-t border-slate-200 bg-white">
      <div className="mx-auto w-full max-w-6xl px-5 py-16 md:px-8 md:py-20">
        <h2 className="max-w-2xl text-3xl font-semibold tracking-tight text-slate-900">
          The unglamorous parts, already handled
        </h2>
        <p className="mt-3 max-w-2xl text-slate-600">
          Most of the work in a voice agent isn’t the prompt. It’s everything around it.
        </p>

        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card transition-shadow hover:shadow-card-hover"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
                <Icon width={18} height={18} />
              </div>
              <h3 className="mt-4 text-base font-semibold text-slate-900">{title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{body}</p>
            </div>
          ))}
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-2xl border border-slate-200 bg-slate-50 px-6 py-4">
          <span className="text-sm font-medium text-slate-700">Also included</span>
          {[
            "Warm-lead retry scheduling",
            "CSV import",
            "Per-agent model choice",
            "Call recordings & history",
          ].map((item) => (
            <span key={item} className="flex items-center gap-1.5 text-sm text-slate-500">
              <ClockIcon width={14} height={14} className="text-slate-400" />
              {item}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
