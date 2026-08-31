import { OutreachStatus, ProspectStatus, ResearchStatus } from "@/lib/types";

export const RESEARCH_META: Record<ResearchStatus, { label: string; tone: "neutral" | "info" | "success" | "danger" }> = {
  pending: { label: "Queued", tone: "neutral" },
  running: { label: "Researching…", tone: "info" },
  ready: { label: "KB ready", tone: "success" },
  failed: { label: "Research failed", tone: "danger" },
};

export const OUTREACH_META: Record<OutreachStatus, { label: string; tone: "neutral" | "info" | "warning" | "danger" }> = {
  not_reached: { label: "Not reached", tone: "neutral" },
  reached: { label: "Reached", tone: "info" },
  callback: { label: "Callback", tone: "warning" },
  do_not_call: { label: "Do not call", tone: "danger" },
};

// The campaign-outcome axis the operator sets by hand. Separate from OUTREACH_META
// above and not synced with it — see backend/models/prospect.py.
export const STATUS_LABELS: Record<ProspectStatus, string> = {
  not_called: "Not called",
  called: "Called",
  booked: "Booked",
  flagged: "Flagged",
  voicemail: "Voicemail",
  no_answer: "No answer",
  do_not_call: "Do not call",
};

export const STATUS_ORDER: ProspectStatus[] = [
  "not_called",
  "called",
  "booked",
  "flagged",
  "voicemail",
  "no_answer",
  "do_not_call",
];
