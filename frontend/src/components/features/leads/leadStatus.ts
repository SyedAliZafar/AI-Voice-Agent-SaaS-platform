import { LeadRetryState, LeadStatus } from "@/lib/types";

// The retry-scheduler axis (ADR-011) — what the automatic caller is doing with this
// lead right now.
export const RETRY_META: Record<
  LeadRetryState,
  { label: string; tone: "neutral" | "info" | "success" | "warning" | "danger" }
> = {
  paused: { label: "Paused", tone: "neutral" },
  scheduled: { label: "Scheduled", tone: "info" },
  in_flight: { label: "Calling…", tone: "warning" },
  succeeded: { label: "Answered", tone: "success" },
  exhausted: { label: "Exhausted", tone: "danger" },
  do_not_call: { label: "Do not call", tone: "danger" },
};

// The operator-set campaign-outcome axis — independent of retry_state, same pattern
// as Prospect.status vs. outreach_status.
export const STATUS_LABELS: Record<LeadStatus, string> = {
  new: "New",
  contacted: "Contacted",
  booked: "Booked",
  not_interested: "Not interested",
  unreachable: "Unreachable",
};

export const STATUS_ORDER: LeadStatus[] = [
  "new",
  "contacted",
  "booked",
  "not_interested",
  "unreachable",
];
