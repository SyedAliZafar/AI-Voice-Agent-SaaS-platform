"use client";

import Link from "next/link";

import { ChevronRightIcon } from "@/components/icons";
import { Skeleton } from "@/components/ui";

/**
 * Whether the connected voice platform is actually reachable, stated plainly on the
 * dashboard. The product's whole premise is "your agents, on Retell" — if that link is
 * down, it's the first thing worth knowing, not something to discover from a failed call.
 *
 * Takes its state as props rather than calling usePlatformAgents itself so the dashboard
 * makes exactly one roster request and can share the result with the setup checklist.
 */
export function RetellStatus({
  loading,
  error,
  agentCount,
}: {
  loading: boolean;
  error: string | null;
  agentCount: number;
}) {
  if (loading) {
    return (
      <div className="mb-6 rounded-xl border border-slate-200 bg-white px-4 py-3">
        <Skeleton className="h-4 w-64" />
      </div>
    );
  }

  const ok = !error;

  return (
    <Link
      href={ok ? "/agents?source=platform" : "/settings"}
      className="mb-6 flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 transition-colors hover:bg-slate-50"
    >
      <span
        className={
          "h-2 w-2 shrink-0 rounded-full " + (ok ? "bg-emerald-500" : "bg-red-500")
        }
      />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-900">
          {ok ? "Connected to Retell" : "Not connected to Retell"}
        </p>
        <p className="truncate text-sm text-slate-500">
          {ok
            ? `${agentCount} agent${agentCount === 1 ? "" : "s"} on the account, ready to dial.`
            : error}
        </p>
      </div>
      <ChevronRightIcon width={16} height={16} className="shrink-0 text-slate-300" />
    </Link>
  );
}
