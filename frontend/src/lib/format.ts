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

/** Maps a sentiment score in [-1, 1] to a color + label. */
export function sentimentMeta(score: number | null): { color: string; label: string } {
  if (score === null) return { color: "bg-slate-300", label: "n/a" };
  if (score >= 0.3) return { color: "bg-emerald-500", label: "Positive" };
  if (score <= -0.3) return { color: "bg-red-500", label: "Negative" };
  return { color: "bg-amber-500", label: "Neutral" };
}
