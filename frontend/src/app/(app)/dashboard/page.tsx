"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { CallTable } from "@/components/features/calls/CallTable";
import { RetellStatus } from "@/components/features/dashboard/RetellStatus";
import { SetupChecklist, SetupStep } from "@/components/features/dashboard/SetupChecklist";
import { SyncNotice } from "@/components/features/dashboard/SyncNotice";
import { CallsIcon, ClockIcon, CheckIcon, LiveIcon, PlusIcon } from "@/components/icons";
import { Button, Card, MetricCard, PageHeader, Skeleton } from "@/components/ui";
import { useAgents } from "@/hooks/useAgents";
import { useCallMetrics } from "@/hooks/useCallMetrics";
import { usePlatformAgents } from "@/hooks/usePlatformAgents";
import { api, getApiErrorMessage } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { Call } from "@/lib/types";
import { workspace } from "@/lib/workspace";

export default function DashboardPage() {
  const router = useRouter();
  const { summary, loading } = useCallMetrics();
  const { agents, loading: agentsLoading } = useAgents();
  const {
    agents: platformAgents,
    loading: platformLoading,
    error: platformError,
  } = usePlatformAgents();

  const [calls, setCalls] = useState<Call[]>([]);
  const [callsLoading, setCallsLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState<string | null>(null);

  function loadCalls() {
    return api
      .get<Call[]>("/calls", { params: { limit: 10 } })
      .then((res) => setCalls(res.data))
      .catch(() => setCalls([]))
      .finally(() => setCallsLoading(false));
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
      setSyncNote(getApiErrorMessage(err, "Could not reach the voice platform."));
    } finally {
      setSyncing(false);
    }
  }

  // Derived from live data, not remembered — see SetupChecklist's docstring.
  const setupSteps: SetupStep[] = [
    {
      // Deliberately not "Connect" with a Connect button: there's no in-app flow to send
      // anyone to. RETELL_API_KEY is a server env var, so the only fix is editing .env —
      // Settings explains that, which is why this points there to *read* rather than act.
      title: "Connect your Retell account",
      body: "Set RETELL_API_KEY on the server so agents can be provisioned and calls placed.",
      href: "/settings",
      cta: "How",
      done: !platformError,
    },
    {
      title: "Build your first agent",
      body: "Answer a few questions and get a full call script written for you.",
      href: "/agents/new",
      cta: "Build",
      done: agents.length > 0,
    },
    {
      title: "Place a test call",
      body: "Try it by text in the sandbox first, then put it on a real line.",
      href: "/agents",
      cta: "Try it",
      done: calls.length > 0,
    },
  ];

  const setupLoading = agentsLoading || platformLoading || callsLoading;

  return (
    <div className="animate-fade-in">
      <PageHeader
        title={`${workspace.name}`}
        subtitle="Your voice agents and what they did today."
        actions={
          <Button
            icon={<PlusIcon width={16} height={16} />}
            onClick={() => router.push("/agents/new")}
          >
            New agent
          </Button>
        }
      />

      {!setupLoading && <SetupChecklist steps={setupSteps} />}

      <RetellStatus
        loading={platformLoading}
        error={platformError}
        agentCount={platformAgents.length}
      />

      <SyncNotice
        count={stuckCount}
        syncing={syncing}
        note={syncNote}
        onSync={syncCalls}
      />

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
            {/* Every figure here is today-only — that's what /analytics/summary returns.
                The scope used to be invisible, which made a quiet morning look like a
                collapse in volume. */}
            <MetricCard
              label="Calls"
              value={summary.total_calls}
              hint="Today"
              icon={<CallsIcon width={16} height={16} />}
            />
            <MetricCard
              label="Avg call length"
              value={formatDuration(summary.avg_duration_sec)}
              hint="Today"
              icon={<ClockIcon width={16} height={16} />}
            />
            <MetricCard
              label="Handled end to end"
              value={`${summary.resolution_rate}%`}
              tone="success"
              hint="Today · no human needed"
              icon={<CheckIcon width={16} height={16} />}
            />
            <MetricCard
              label="Passed to a human"
              value={summary.escalated_count}
              tone="warning"
              hint="Today"
              icon={<LiveIcon width={16} height={16} />}
            />
          </>
        )}
      </div>

      <Card className="p-5">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-sm font-semibold text-slate-900">Recent calls</p>
          <Link href="/calls" className="text-xs font-medium text-brand-600 hover:text-brand-700">
            View all →
          </Link>
        </div>
        <CallTable calls={calls} />
      </Card>
    </div>
  );
}
