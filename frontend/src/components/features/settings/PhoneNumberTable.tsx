"use client";

import { Badge, Skeleton } from "@/components/ui";
import { PlatformAgent, PlatformPhoneNumber } from "@/lib/types";

/**
 * The numbers actually on the voice platform account, fetched live.
 *
 * This replaced two invented numbers ("+1 (415) 555-0142", assigned to a "Sales
 * qualifier" agent that never existed) — the same class of error as the hardcoded green
 * "Connected" badge this page used to show for Retell.
 *
 * The agent columns resolve platform agent ids to names using the roster the page has
 * already fetched, falling back to the raw id: an id is a poor label, but a blank cell
 * would read as "unassigned", which is a different and materially wrong claim.
 */
export function PhoneNumberTable({
  numbers,
  agents,
  loading,
  error,
}: {
  numbers: PlatformPhoneNumber[];
  agents: PlatformAgent[];
  loading: boolean;
  error: string | null;
}) {
  const agentName = (id: string | null) => {
    if (!id) return null;
    return agents.find((a) => a.external_id === id)?.name ?? id;
  };

  if (loading) {
    return (
      <div className="space-y-2 p-3">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <p className="p-4 text-sm text-red-600">
        {error} Numbers are read from the voice platform, so this list is empty rather
        than stale when it can&apos;t be reached.
      </p>
    );
  }

  if (numbers.length === 0) {
    return (
      <p className="p-4 text-sm text-slate-500">
        No numbers on this voice platform account. Buy or import one in the platform&apos;s
        own dashboard — there is no in-app purchase flow.
      </p>
    );
  }

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs font-medium uppercase tracking-wide text-slate-400">
          <th className="px-3 py-2 font-medium">Number</th>
          <th className="px-3 py-2 font-medium">Label</th>
          <th className="px-3 py-2 font-medium">Answers calls</th>
          <th className="px-3 py-2 font-medium">Calls out</th>
        </tr>
      </thead>
      <tbody>
        {numbers.map((n) => {
          const inbound = agentName(n.inbound_agent_id);
          const outbound = agentName(n.outbound_agent_id);
          return (
            <tr key={n.number} className="border-t border-slate-50">
              <td className="px-3 py-2.5 font-mono text-[13px] text-slate-700">{n.pretty}</td>
              <td className="px-3 py-2.5 text-slate-600">
                {n.nickname ?? <span className="text-slate-400">—</span>}
                {/* Both ends unassigned: the number is being paid for and answers
                    nothing. That's the actionable case, so it's called out rather than
                    left as two empty cells to notice. */}
                {!inbound && !outbound && (
                  <Badge tone="warning" className="ml-2">
                    Unassigned
                  </Badge>
                )}
              </td>
              <td className="px-3 py-2.5 text-slate-600">
                {inbound ?? <span className="text-slate-400">—</span>}
              </td>
              <td className="px-3 py-2.5 text-slate-600">
                {outbound ?? <span className="text-slate-400">—</span>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
