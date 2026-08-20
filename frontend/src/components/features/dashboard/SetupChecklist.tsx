"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { CheckIcon, ChevronRightIcon } from "@/components/icons";

const DISMISS_KEY = "setup_checklist_dismissed";

export interface SetupStep {
  title: string;
  body: string;
  href: string;
  cta: string;
  done: boolean;
}

/**
 * First-run guidance on the dashboard. Hidden once every step is done, and dismissible
 * before that — an operator who deliberately skipped a step shouldn't be nagged forever.
 *
 * Each step's `done` is derived from real data by the caller (an agent exists, a call
 * exists, Retell answered), never stored: a checklist that ticks itself off from
 * localStorage lies the moment someone deletes the agent it was pointing at.
 */
export function SetupChecklist({ steps }: { steps: SetupStep[] }) {
  const [dismissed, setDismissed] = useState(true);

  // Read after mount — localStorage isn't available during SSR, and rendering the card
  // on the server then hiding it on hydration causes a visible flash.
  useEffect(() => {
    setDismissed(window.localStorage.getItem(DISMISS_KEY) === "1");
  }, []);

  function dismiss() {
    window.localStorage.setItem(DISMISS_KEY, "1");
    setDismissed(true);
  }

  const doneCount = steps.filter((s) => s.done).length;
  if (dismissed || doneCount === steps.length) return null;

  return (
    <div className="mb-6 overflow-hidden rounded-2xl border border-brand-200 bg-gradient-to-br from-brand-50 to-white">
      <div className="flex items-start justify-between gap-4 px-5 pt-5">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Finish setting up</h2>
          <p className="mt-0.5 text-sm text-slate-600">
            {doneCount} of {steps.length} done — a few minutes to your first live call.
          </p>
        </div>
        <button
          onClick={dismiss}
          className="shrink-0 rounded-lg px-2 py-1 text-xs font-medium text-slate-500 transition-colors hover:bg-white hover:text-slate-800"
        >
          Dismiss
        </button>
      </div>

      <ol className="mt-4 divide-y divide-brand-100/70 border-t border-brand-100/70">
        {steps.map((step) => (
          <li key={step.title} className="flex items-center gap-3.5 px-5 py-3.5">
            <span
              className={
                "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border " +
                (step.done
                  ? "border-emerald-500 bg-emerald-500 text-white"
                  : "border-slate-300 bg-white")
              }
            >
              {step.done && <CheckIcon width={13} height={13} />}
            </span>

            <div className="min-w-0 flex-1">
              <p
                className={
                  "text-sm font-medium " +
                  (step.done ? "text-slate-400 line-through" : "text-slate-900")
                }
              >
                {step.title}
              </p>
              {!step.done && <p className="text-sm text-slate-500">{step.body}</p>}
            </div>

            {!step.done && (
              <Link
                href={step.href}
                className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-white px-3 py-1.5 text-sm font-medium text-brand-700 shadow-sm ring-1 ring-brand-200 transition-colors hover:bg-brand-50"
              >
                {step.cta}
                <ChevronRightIcon width={14} height={14} />
              </Link>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
