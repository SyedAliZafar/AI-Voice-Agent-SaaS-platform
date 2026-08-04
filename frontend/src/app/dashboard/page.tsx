"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { CallTable } from "@/components/CallTable";
import { MetricCard } from "@/components/MetricCard";
import { CallsIcon, ClockIcon, CheckIcon, LiveIcon } from "@/components/icons";
import { Button, Card, PageHeader, Skeleton } from "@/components/ui";
import { useCallMetrics } from "@/hooks/useCallMetrics";
import { api, getApiErrorMessage } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { Call } from "@/lib/types";

export default function DashboardPage() {
  const { summary, loading } = useCallMetrics();
  const [calls, setCalls] = useState<Call[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState<string | null>(null);

  function loadCalls() {
    return api
      .get<Call[]>("/calls", { params: { limit: 10 } })
      .then((res) => setCalls(res.data))
      .catch(() => setCalls([]));
  }

  useEffect(() => {
    loadCalls();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stuckCount = useMemo(
    () => calls.filter((c) => c.status === "in_progress").length,
    [calls],
  );

  // Same rationale as the Calls page: a webhook resolving a call server-side never
  // reaches an already-open tab on its own. Only runs while something's in flight.
  useEffect(() => {
    if (stuckCount === 0) return;
    const id = setInterval(loadCalls, 8000);
    return () => clearInterval(id);
  }, [stuckCount]);

  async function syncCalls() {
    setSyncing(true);
    setSyncNote(null);
    try {
      const res = await api.post<{ updated: number }>("/calls/sync");
      await loadCalls();
      setSyncNote(
        res.data.updated > 0
          ? `Updated ${res.data.updated} call${res.data.updated === 1 ? "" : "s"}.`
          : "No changes — the platform still reports these as active.",
      );
    } catch (err) {
      setSyncNote(getApiErrorMessage(err, "Sync failed. Check the backend logs."));
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="animate-fade-in">
      <PageHeader title="Dashboard" subtitle="Today's voice agent activity at a glance." />

      {stuckCount > 0 && (
        <div className="mb-6 flex flex-col gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-amber-800">
            {stuckCount} call{stuckCount === 1 ? " is" : "s are"} stuck at &ldquo;in
            progress&rdquo; — usually a missed webhook (dead tunnel, unset{" "}
            <code className="rounded bg-amber-100 px-1 py-0.5 text-xs">PUBLIC_BASE_URL</code>).
            Reconciling pulls the real status from the voice platform.
          </p>
          <div className="flex items-center gap-2">
            {syncNote && <span className="text-xs text-amber-700">{syncNote}</span>}
            <Button variant="secondary" size="sm" onClick={syncCalls} disabled={syncing}>
              {syncing ? "Syncing…" : "Sync status"}
            </Button>
          </div>
        </div>
      )}

      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {loading || !summary ? (
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card p-5">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-4 h-8 w-16" />
            </div>
          ))
        ) : (
          <>
            <MetricCard
              label="Total calls today"
              value={summary.total_calls}
              icon={<CallsIcon width={16} height={16} />}
            />
            <MetricCard
              label="Avg duration"
              value={formatDuration(summary.avg_duration_sec)}
              icon={<ClockIcon width={16} height={16} />}
            />
            <MetricCard
              label="Resolution rate"
              value={`${summary.resolution_rate}%`}
              tone="success"
              icon={<CheckIcon width={16} height={16} />}
            />
            <MetricCard
              label="Escalated"
              value={summary.escalated_count}
              tone="warning"
              icon={<LiveIcon width={16} height={16} />}
            />
          </>
        )}
      </div>

      <Card className="p-5">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-sm font-semibold text-slate-900">Recent calls</p>
          <Link
            href="/calls"
            className="text-xs font-medium text-brand-600 hover:text-brand-700"
          >
            View all →
          </Link>
        </div>
        <CallTable calls={calls} />
      </Card>
    </div>
  );
}
