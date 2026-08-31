import { Card } from "@/components/ui";
import { ProspectStats } from "@/lib/types";

// Counts shown in the strip, in order. "total" plus the four outcomes worth
// watching — not_called and do_not_call are deliberately left off (they're the
// residue, and the per-row status dropdown already shows them).
const STAT_TILES: { key: keyof ProspectStats; label: string }[] = [
  { key: "total", label: "Total" },
  { key: "called", label: "Called" },
  { key: "voicemail", label: "Voicemail" },
  { key: "booked", label: "Booked" },
  { key: "flagged", label: "Flagged" },
  { key: "no_answer", label: "No answer" },
];

export function ProspectStatsStrip({ stats }: { stats: ProspectStats }) {
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
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
