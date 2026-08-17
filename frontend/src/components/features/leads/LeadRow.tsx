"use client";

import { RETRY_META, STATUS_LABELS, STATUS_ORDER } from "@/components/features/leads/leadStatus";
import { LeadDetailPanel } from "@/components/features/leads/LeadDetailPanel";
import { Badge, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { Agent, Lead, LeadStatus } from "@/lib/types";

export function LeadRow({
  lead,
  agents,
  expanded,
  onToggleExpand,
  onChanged,
}: {
  lead: Lead;
  agents: Agent[];
  expanded: boolean;
  onToggleExpand: () => void;
  onChanged: () => void;
}) {
  const retry = RETRY_META[lead.retry_state];
  const isActive = lead.retry_state === "scheduled" || lead.retry_state === "in_flight";
  const canStart = lead.retry_state === "paused" || lead.retry_state === "exhausted";
  const canPause = lead.retry_state === "scheduled";

  async function setStatus(status: LeadStatus) {
    await api.patch(`/leads/${lead.id}`, { status });
    onChanged();
  }

  async function start() {
    await api.post(`/leads/${lead.id}/start`);
    onChanged();
  }

  async function pause() {
    await api.post(`/leads/${lead.id}/pause`);
    onChanged();
  }

  async function doNotCall() {
    await api.post(`/leads/${lead.id}/do-not-call`);
    onChanged();
  }

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate font-medium text-slate-900">
              {lead.business_name || lead.contact_name || lead.phone}
            </p>
            <span className="text-xs text-slate-400">{lead.source}</span>
          </div>
          <p className="mt-0.5 truncate text-xs text-slate-500">
            {[lead.contact_name, lead.phone, lead.city].filter(Boolean).join(" · ")}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Badge tone={retry.tone}>{retry.label}</Badge>

          <select
            aria-label={`Status for ${lead.business_name || lead.phone}`}
            value={lead.status}
            onChange={(e) => setStatus(e.target.value as LeadStatus)}
            className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 focus:border-brand-300 focus:outline-none"
          >
            {STATUS_ORDER.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>

          {canStart && lead.retry_state !== "do_not_call" && (
            <Button variant="secondary" size="sm" onClick={start}>
              {lead.retry_state === "exhausted" ? "Retry" : "Start calling"}
            </Button>
          )}
          {canPause && (
            <Button variant="ghost" size="sm" onClick={pause}>
              Pause
            </Button>
          )}
          {lead.retry_state !== "do_not_call" && (
            <Button variant="ghost" size="sm" onClick={doNotCall}>
              Do not call
            </Button>
          )}

          <Button
            variant={expanded ? "secondary" : "primary"}
            size="sm"
            onClick={onToggleExpand}
          >
            {expanded ? "Close" : "Details"}
          </Button>
        </div>
      </div>

      {isActive && lead.next_attempt_at && (
        <p className="mt-2 text-xs text-slate-400">
          Next attempt: {new Date(lead.next_attempt_at).toLocaleString()} · attempt{" "}
          {lead.attempt_count + 1}
        </p>
      )}

      {expanded && <LeadDetailPanel lead={lead} agents={agents} onChanged={onChanged} />}
    </Card>
  );
}
