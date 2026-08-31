"use client";

import { ProspectStats, ProspectStatus } from "@/lib/types";

/** The section rail above the prospect list. "All" plus one tab per campaign-outcome
 * status, so the operator can jump straight to "who went to voicemail" or "who we
 * actually spoke to" — the split the flat list couldn't show.
 *
 * URL-param backed by the parent (`section`), same pattern as ProspectFilters: the
 * active tab survives a refresh and is shareable. Counts come from /prospects/stats,
 * which is aggregated server-side and so stays correct past the list's 500-row cap.
 */
export type ProspectSection = "all" | ProspectStatus;

const SECTIONS: { key: ProspectSection; label: string; statKey: keyof ProspectStats }[] = [
  { key: "all", label: "All", statKey: "total" },
  { key: "not_called", label: "Not called", statKey: "not_called" },
  { key: "voicemail", label: "Voicemail", statKey: "voicemail" },
  { key: "called", label: "Called", statKey: "called" },
  { key: "no_answer", label: "No answer", statKey: "no_answer" },
  { key: "booked", label: "Booked", statKey: "booked" },
  { key: "flagged", label: "Flagged", statKey: "flagged" },
  { key: "do_not_call", label: "Do not call", statKey: "do_not_call" },
];

export function ProspectSectionTabs({
  active,
  stats,
  onChange,
}: {
  active: ProspectSection;
  stats: ProspectStats | null;
  onChange: (section: ProspectSection) => void;
}) {
  return (
    <div className="mb-4 flex flex-wrap gap-2" role="tablist" aria-label="Prospect sections">
      {SECTIONS.map(({ key, label, statKey }) => {
        const isActive = key === active;
        const count = stats ? stats[statKey] : null;
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(key)}
            className={
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors " +
              (isActive
                ? "border-brand-300 bg-brand-50 text-brand-700"
                : "border-slate-200 text-slate-600 hover:border-slate-300 hover:text-slate-900")
            }
          >
            {label}
            {count != null && (
              <span className="ml-1.5 tabular-nums text-slate-400">{count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
