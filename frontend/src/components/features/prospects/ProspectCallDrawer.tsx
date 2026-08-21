"use client";

import { useEffect } from "react";

import { ProspectDetailPanel } from "@/components/features/prospects/ProspectDetailPanel";
import { OUTREACH_META, RESEARCH_META } from "@/components/features/prospects/prospectStatus";
import { CloseIcon } from "@/components/icons";
import { Badge } from "@/components/ui";
import { Agent, Prospect } from "@/lib/types";

/**
 * The call form as a fixed right-side panel, not a row expanding inline.
 *
 * /prospects re-groups by country/category/city on every render (lib/prospectGrouping),
 * and a prospect's group membership changes the moment research fills in its city —
 * which means the row it lives in can relocate to a different branch of the tree while
 * an operator is mid-form. React unmounts/remounts across that move (it's a different
 * parent, not a reorder within one), taking focus and scroll position with it — the
 * "cursor jumps away" complaint. Pinning the form to the viewport instead of the row
 * means the background list can re-sort itself freely; the drawer's own position never
 * moves, because it isn't part of that tree.
 *
 * Owns none of the "which prospect" state — the page passes the current prospect object
 * (or null to stay closed) and a close handler, same lifted-state pattern the rest of
 * this app uses for anything that must survive its trigger re-rendering.
 */
export function ProspectCallDrawer({
  prospect,
  agents,
  onClose,
  onChanged,
}: {
  prospect: Prospect | null;
  agents: Agent[];
  onClose: () => void;
  onChanged: () => void;
}) {
  useEffect(() => {
    if (!prospect) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [prospect, onClose]);

  if (!prospect) return null;

  const research = RESEARCH_META[prospect.research_status];
  const outreach = OUTREACH_META[prospect.outreach_status];

  return (
    <>
      <div
        className="fixed inset-0 z-30 bg-slate-900/20 backdrop-blur-[1px]"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Call ${prospect.name}`}
        className="animate-fade-in fixed inset-y-0 right-0 z-40 flex w-full max-w-lg flex-col border-l border-slate-200 bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div className="min-w-0">
            <p className="truncate text-base font-semibold text-slate-900">{prospect.name}</p>
            <div className="mt-1.5 flex items-center gap-2">
              <Badge tone={research.tone}>{research.label}</Badge>
              <Badge tone={outreach.tone}>{outreach.label}</Badge>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
          >
            <CloseIcon width={18} height={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <ProspectDetailPanel prospect={prospect} agents={agents} onChanged={onChanged} bare />
        </div>
      </div>
    </>
  );
}
