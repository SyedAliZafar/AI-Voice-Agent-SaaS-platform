"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { CallTable } from "@/components/CallTable";
import { MetricCard } from "@/components/MetricCard";
import { CallsIcon, ClockIcon, CheckIcon, LiveIcon } from "@/components/icons";
import { Card, PageHeader, Skeleton } from "@/components/ui";
import { useCallMetrics } from "@/hooks/useCallMetrics";
import { api } from "@/lib/api";
import { DEMO_TENANT_ID } from "@/lib/constants";
import { formatDuration } from "@/lib/format";
import { Call } from "@/lib/types";

const TENANT_ID = DEMO_TENANT_ID; // replace with real auth-derived tenant id

export default function DashboardPage() {
  const { summary, loading } = useCallMetrics(TENANT_ID);
  const [calls, setCalls] = useState<Call[]>([]);

  useEffect(() => {
    api
      .get<Call[]>("/calls", { params: { tenant_id: TENANT_ID, limit: 10 } })
      .then((res) => setCalls(res.data))
      .catch(() => setCalls([]));
  }, []);

  return (
    <div className="animate-fade-in">
      <PageHeader title="Dashboard" subtitle="Today's voice agent activity at a glance." />

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
