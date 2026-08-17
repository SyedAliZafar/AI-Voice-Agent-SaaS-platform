import { Card } from "@/components/ui";
import { LeadStats } from "@/lib/types";

const STAT_TILES: { key: keyof LeadStats; label: string }[] = [
  { key: "total", label: "Total" },
  { key: "scheduled", label: "Scheduled" },
  { key: "in_flight", label: "Calling" },
  { key: "succeeded", label: "Answered" },
  { key: "exhausted", label: "Exhausted" },
];

export function LeadStatsStrip({ stats }: { stats: LeadStats }) {
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
      {STAT_TILES.map(({ key, label }) => (
        <Card key={key} className="p-3">
          <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
          <p className="mt-0.5 text-2xl font-semibold tabular-nums text-slate-900">
            {stats[key]}
          </p>
        </Card>
      ))}
    </div>
  );
}
