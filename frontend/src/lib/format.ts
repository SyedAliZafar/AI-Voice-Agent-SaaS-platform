import { Call } from "@/lib/types";

export function formatDuration(totalSec: number): string {
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}m ${s}s`;
}

/** Quick per-minute estimate (see backend Settings.call_cost_per_minute), not an
 * itemized bill — shown with more precision below $0.01 so short calls don't all
 * round down to "$0.00". */
export function formatCost(usd: number): string {
  return `$${usd.toFixed(usd < 0.01 && usd > 0 ? 4 : 2)}`;
}

type StatusMeta = {
  label: string;
  badge: string; // tailwind classes for the pill
  dot: string; // tailwind bg for the status dot
};

export const CALL_STATUS_META: Record<Call["status"], StatusMeta> = {
  resolved: { label: "Resolved", badge: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" },
  escalated: { label: "Escalated", badge: "bg-amber-50 text-amber-700", dot: "bg-amber-500" },
  in_progress: { label: "In progress", badge: "bg-blue-50 text-blue-700", dot: "bg-blue-500" },
  failed: { label: "Failed", badge: "bg-red-50 text-red-700", dot: "bg-red-500" },
};

/** Plain-English labels for Retell's `disconnection_reason`, which the backend stores
 * verbatim alongside the coarse `status`.
 *
 * This exists because `status` deliberately collapses every non-conversational ending
 * into "failed" — a voicemail, a declined call and a phone that rang out are the same
 * word on screen, and they mean completely different things to whoever has to decide
 * whether to call again. Only reasons that are genuinely ambiguous-looking are
 * translated; anything unlisted falls back to the raw string (de-underscored) rather
 * than being hidden, so a reason Retell adds later still shows up.
 *
 * Kept in sync by hand with call_service's _FAILURE_REASONS / _TRANSFER_REASONS, same
 * convention as lib/types.ts. */
const DISCONNECTION_LABELS: Record<string, string> = {
  user_hangup: "The person hung up",
  agent_hangup: "The agent ended the call",
  call_transfer: "Transferred to a human",
  voicemail_reached: "Reached voicemail",
  machine_detected: "An answering machine picked up",
  dial_no_answer: "Rang out — nobody answered",
  dial_busy: "Line was busy",
  dial_failed: "The call could not be placed",
  user_declined: "The person declined the call",
  invalid_destination: "Not a valid number",
  marked_as_spam: "The carrier flagged this call as spam",
  scam_detected: "Blocked as a suspected scam call",
  registered_call_timeout: "Timed out before connecting",
  concurrency_limit_reached: "Blocked — too many calls at once",
  no_concurrency_fallback: "Blocked — too many calls at once",
  telephony_provider_unavailable: "The phone provider was unavailable",
  telephony_provider_permission_denied: "The phone provider refused the call",
  sip_routing_error: "Could not be routed",
  no_valid_payment: "Blocked — billing problem on the voice platform",
};

export function disconnectionLabel(reason: string | null): string | null {
  if (!reason) return null;
  if (DISCONNECTION_LABELS[reason]) return DISCONNECTION_LABELS[reason];
  if (reason.startsWith("error")) return "Ended with an error on the platform";
  return reason.replace(/_/g, " ");
}

/** Did a person actually talk on this call?
 *
 * The subtlety worth preserving on screen: an answering machine's greeting transcribes
 * as a caller turn, so `answered_by_human` is true for voicemails. `disconnection_reason`
 * carries Retell's own machine detection and is authoritative, so it is checked first —
 * the same order prospect_service uses when classifying an outcome. Getting this
 * backwards once put a whole campaign of voicemails in "called". */
export function answeredLabel(
  answeredByHuman: boolean | null,
  reason: string | null,
): { label: string; tone: "success" | "warning" | "neutral" } {
  if (reason === "voicemail_reached" || reason === "machine_detected") {
    return { label: "Voicemail — not a person", tone: "warning" };
  }
  if (answeredByHuman === true) return { label: "A person spoke", tone: "success" };
  if (answeredByHuman === false) return { label: "Nobody spoke", tone: "warning" };
  return { label: "Unknown", tone: "neutral" };
}

/** Maps a sentiment score in [-1, 1] to a color + label. */
export function sentimentMeta(score: number | null): { color: string; label: string } {
  if (score === null) return { color: "bg-slate-300", label: "n/a" };
  if (score >= 0.3) return { color: "bg-emerald-500", label: "Positive" };
  if (score <= -0.3) return { color: "bg-red-500", label: "Negative" };
  return { color: "bg-amber-500", label: "Neutral" };
}
