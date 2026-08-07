"use client";

import { useEffect, useMemo, useState } from "react";

import { CallTable } from "@/components/features/calls/CallTable";
import { CallsIcon, SearchIcon } from "@/components/icons";
import { Button, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui";
import { api, getApiErrorMessage } from "@/lib/api";
import { Call } from "@/lib/types";

const FILTERS: { value: "all" | Call["status"]; label: string }[] = [
  { value: "all", label: "All" },
  { value: "resolved", label: "Resolved" },
  { value: "escalated", label: "Escalated" },
  { value: "in_progress", label: "In progress" },
  { value: "failed", label: "Failed" },
];

export default function CallsPage() {
  const [calls, setCalls] = useState<Call[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<"all" | Call["status"]>("all");
  const [query, setQuery] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState<string | null>(null);

  function loadCalls() {
    return api
      .get<Call[]>("/calls", { params: { limit: 100 } })
      .then((res) => setCalls(res.data))
      .catch(() => setCalls([]))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadCalls();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stuckCount = useMemo(
    () => calls.filter((c) => c.status === "in_progress").length,
    [calls],
  );

  // A webhook resolving a call server-side never reaches an already-open tab on its
  // own — without this, "is it still in progress?" is a question the user can only
  // answer by manually reloading. Only runs while something's actually in flight.
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

  const filtered = useMemo(() => {
    return calls.filter((c) => {
      const matchesStatus = status === "all" || c.status === status;
      const matchesQuery = !query || c.caller_number.includes(query.trim());
      return matchesStatus && matchesQuery;
    });
  }, [calls, status, query]);

  return (
    <div className="animate-fade-in">
      <PageHeader title="Calls" subtitle="Full call history across all agents." />

      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => {
            const active = status === f.value;
            return (
              <button
                key={f.value}
                onClick={() => setStatus(f.value)}
                className={
                  "rounded-full px-3 py-1.5 text-xs font-medium transition-colors " +
                  (active
                    ? "bg-brand-600 text-white"
                    : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50")
                }
              >
                {f.label}
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-2">
          <div className="relative sm:w-64">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">
              <SearchIcon width={16} height={16} />
            </span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by number"
              className="w-full rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none"
            />
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={syncCalls}
            disabled={syncing || stuckCount === 0}
            title={
              stuckCount === 0
                ? "No calls are still in progress"
                : `Re-check ${stuckCount} in-progress call${stuckCount === 1 ? "" : "s"} against the voice platform`
            }
          >
            {syncing ? "Syncing…" : "Sync status"}
          </Button>
        </div>
      </div>

      {syncNote && <p className="mb-3 text-xs text-slate-500">{syncNote}</p>}

      <Card className="p-5">
        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<CallsIcon />}
            title="No calls found"
            description={
              calls.length === 0
                ? "Calls will appear here once your agents start taking them."
                : "No calls match the current filters."
            }
          />
        ) : (
          <CallTable calls={filtered} />
        )}
      </Card>
    </div>
  );
}
