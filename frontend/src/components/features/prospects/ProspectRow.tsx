"use client";

import { useRouter } from "next/navigation";

import { OUTREACH_META, RESEARCH_META, STATUS_LABELS, STATUS_ORDER } from "@/components/features/prospects/prospectStatus";
import { RefreshIcon } from "@/components/icons";
import { Badge, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { Prospect, ProspectStatus } from "@/lib/types";

export function ProspectRow({
  prospect,
  isOpen,
  onOpenCall,
  onChanged,
}: {
  prospect: Prospect;
  /** Whether this row's call drawer (ProspectCallDrawer, rendered by the page) is the
   * one currently open — purely for the button's pressed styling, the drawer itself
   * lives outside this row so re-grouping the list can't carry it away mid-form. */
  isOpen: boolean;
  onOpenCall: () => void;
  onChanged: () => void;
}) {
  const router = useRouter();
  const research = RESEARCH_META[prospect.research_status];
  const outreach = OUTREACH_META[prospect.outreach_status];
  const ready = prospect.research_status === "ready";

  // "Called N× · last called <date time>" — shown only once a call has actually
  // landed, so the not-called queue stays clean. last_called_at is an ISO string from
  // the API; toLocaleString matches how LeadRow / LeadDetailPanel render timestamps.
  const callHistory =
    prospect.call_count > 0
      ? `Called ${prospect.call_count}×` +
        (prospect.last_called_at
          ? ` · last called ${new Date(prospect.last_called_at).toLocaleString(undefined, {
              dateStyle: "medium",
              timeStyle: "short",
            })}`
          : "")
      : null;

  async function setStatus(status: ProspectStatus) {
    await api.patch(`/prospects/${prospect.id}`, { status });
    onChanged();
  }

  async function rerunResearch() {
    await api.post(`/prospects/${prospect.id}/research`);
    onChanged();
  }

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate font-medium text-slate-900">{prospect.name}</p>
            <span className="text-xs text-slate-400 tabular-nums">
              priority {prospect.priority_score.toFixed(2)}
            </span>
          </div>
          <p className="mt-0.5 truncate text-xs text-slate-500">
            {[prospect.city, prospect.address].filter(Boolean).join(" · ") || "—"}
            {prospect.rating != null && ` · ★ ${prospect.rating} (${prospect.review_count})`}
          </p>
          {callHistory && (
            <p className="mt-0.5 truncate text-xs text-slate-400 tabular-nums">{callHistory}</p>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Badge tone={research.tone}>{research.label}</Badge>
          <Badge tone={outreach.tone}>{outreach.label}</Badge>

          <select
            aria-label={`Status for ${prospect.name}`}
            value={prospect.status}
            onChange={(e) => setStatus(e.target.value as ProspectStatus)}
            className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 focus:border-brand-300 focus:outline-none"
          >
            {STATUS_ORDER.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>

          {prospect.research_status === "failed" && (
            <Button
              variant="ghost"
              size="sm"
              icon={<RefreshIcon width={14} height={14} />}
              onClick={rerunResearch}
            >
              Retry
            </Button>
          )}

          <Button
            variant="secondary"
            size="sm"
            onClick={() => router.push(`/prospects/${prospect.id}/sandbox`)}
            disabled={!ready}
            title="Read how the call would go, over text — no phone call"
          >
            Sandbox chat
          </Button>

          {/* Not gated on research, unlike Sandbox chat: the drawer also offers Retell
              dashboard agents (ADR-012), which carry their own script and need no
              [COMPANY BRIEF] — so an un-researched prospect is still callable, just not
              with a personalized agent. The drawer enforces that distinction itself. */}
          <Button variant={isOpen ? "secondary" : "primary"} size="sm" onClick={onOpenCall}>
            Call
          </Button>
        </div>
      </div>
    </Card>
  );
}
