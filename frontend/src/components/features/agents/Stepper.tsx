"use client";

import { CheckIcon } from "@/components/icons";

export function Stepper({
  steps,
  current,
  onStepClick,
}: {
  steps: string[];
  current: number;
  onStepClick?: (index: number) => void;
}) {
  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-3">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={label} className="flex items-center gap-2">
            <button
              type="button"
              disabled={i > current}
              onClick={() => onStepClick?.(i)}
              className={
                "flex items-center gap-2 rounded-full py-1 pl-1 pr-3 text-xs font-medium transition-colors " +
                (active
                  ? "bg-brand-50 text-brand-700"
                  : done
                    ? "text-slate-600 hover:bg-slate-50"
                    : "text-slate-400")
              }
            >
              <span
                className={
                  "flex h-6 w-6 items-center justify-center rounded-full text-[11px] " +
                  (active
                    ? "bg-brand-600 text-white"
                    : done
                      ? "bg-emerald-500 text-white"
                      : "border border-slate-200 bg-white text-slate-400")
                }
              >
                {done ? <CheckIcon width={12} height={12} /> : i + 1}
              </span>
              {label}
            </button>
            {i < steps.length - 1 && <span className="h-px w-4 bg-slate-200" />}
          </li>
        );
      })}
    </ol>
  );
}
