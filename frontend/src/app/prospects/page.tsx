"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Field, TextInput } from "@/components/form";
import { RefreshIcon, SearchIcon, TargetIcon } from "@/components/icons";
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui";
import { api, getApiErrorMessage } from "@/lib/api";
import { Agent, OutreachStatus, Prospect, ResearchStatus } from "@/lib/types";

const RESEARCH_META: Record<ResearchStatus, { label: string; tone: "neutral" | "info" | "success" | "danger" }> = {
  pending: { label: "Queued", tone: "neutral" },
  running: { label: "Researching…", tone: "info" },
  ready: { label: "KB ready", tone: "success" },
  failed: { label: "Research failed", tone: "danger" },
};

const OUTREACH_META: Record<OutreachStatus, { label: string; tone: "neutral" | "info" | "warning" | "danger" }> = {
  not_reached: { label: "Not reached", tone: "neutral" },
  reached: { label: "Reached", tone: "info" },
  callback: { label: "Callback", tone: "warning" },
  do_not_call: { label: "Do not call", tone: "danger" },
};

export default function ProspectsPage() {
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);

  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [callAgentId, setCallAgentId] = useState<string>("");
  const [callNumber, setCallNumber] = useState("");
  const [callingId, setCallingId] = useState<string | null>(null);
  const [callFeedback, setCallFeedback] = useState<Record<string, string>>({});

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchProspects = useCallback(async () => {
    const res = await api.get<Prospect[]>("/prospects");
    setProspects(res.data);
    return res.data;
  }, []);

  useEffect(() => {
    fetchProspects()
      .catch(() => setProspects([]))
      .finally(() => setLoading(false));

    api
      .get<Agent[]>("/agents")
      .then((res) => {
        setAgents(res.data);
        const retellAgent = res.data.find((a) => a.platform === "retell");
        if (retellAgent) setCallAgentId(retellAgent.id);
      })
      .catch(() => setAgents([]));
  }, [fetchProspects]);

  // While anything is still pending/running research, poll so rows flip to "KB ready" live.
  useEffect(() => {
    const hasInFlight = prospects.some(
      (p) => p.research_status === "pending" || p.research_status === "running",
    );
    if (hasInFlight && !pollRef.current) {
      pollRef.current = setInterval(() => {
        fetchProspects().catch(() => {});
      }, 4000);
    }
    if (!hasInFlight && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [prospects, fetchProspects]);

  async function runDiscovery() {
    setDiscovering(true);
    try {
      await api.post(
        "/prospects/discover",
        { query, location: location || null, radius_m: 20000, limit: 20 },
      );
      // Discovery + research run in the background — refresh shortly after to catch new rows.
      setTimeout(() => fetchProspects().catch(() => {}), 1500);
    } finally {
      setDiscovering(false);
    }
  }

  async function rerunResearch(id: string) {
    await api.post(`/prospects/${id}/research`);
    fetchProspects().catch(() => {});
  }

  async function setOutreach(id: string, outreach_status: OutreachStatus) {
    await api.patch(`/prospects/${id}`, { outreach_status });
    fetchProspects().catch(() => {});
  }

  function openCallPanel(prospect: Prospect) {
    setExpandedId(expandedId === prospect.id ? null : prospect.id);
    setCallNumber(prospect.phone || "");
    setCallFeedback((prev) => ({ ...prev, [prospect.id]: "" }));
  }

  async function placeCall(prospect: Prospect) {
    if (!callAgentId || !callNumber) return;
    setCallingId(prospect.id);
    try {
      const res = await api.post(`/prospects/${prospect.id}/call`, {
        agent_id: callAgentId,
        to_number: callNumber,
      });
      setCallFeedback((prev) => ({
        ...prev,
        [prospect.id]: `Dialing from ${res.data.from_number} · call ${res.data.call_id.slice(0, 12)}…`,
      }));
      fetchProspects().catch(() => {});
    } catch (err) {
      const message = getApiErrorMessage(err, "Failed to place call.");
      setCallFeedback((prev) => ({ ...prev, [prospect.id]: message }));
    } finally {
      setCallingId(null);
    }
  }

  const retellAgents = agents.filter((a) => a.platform === "retell");

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Prospects"
        subtitle="Discovery finds companies, research builds their knowledge base — you just pick who to call."
      />

      <Card className="mb-6 p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <Field label="What are you looking for">
            <TextInput
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="dentists, marketing agencies, gyms…"
            />
          </Field>
          <Field label="Where">
            <TextInput
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Berlin, Germany"
            />
          </Field>
          <div className="flex items-end pb-4">
            <Button
              icon={<SearchIcon width={16} height={16} />}
              onClick={runDiscovery}
              disabled={discovering || !query}
            >
              {discovering ? "Starting…" : "Find companies"}
            </Button>
          </div>
        </div>
        <p className="text-xs text-slate-400">
          Discovery and research run automatically in the background — this page updates as
          companies are found and their knowledge base is built.
        </p>
      </Card>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-xl" />
          ))}
        </div>
      ) : prospects.length === 0 ? (
        <EmptyState
          icon={<TargetIcon />}
          title="No prospects yet"
          description="Run a search above to find companies to call."
        />
      ) : (
        <div className="space-y-3">
          {prospects.map((prospect) => {
            const research = RESEARCH_META[prospect.research_status];
            const outreach = OUTREACH_META[prospect.outreach_status];
            const ready = prospect.research_status === "ready";
            const expanded = expandedId === prospect.id;

            return (
              <Card key={prospect.id} className="p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate font-medium text-slate-900">{prospect.name}</p>
                      <span className="text-xs text-slate-400 tabular-nums">
                        priority {prospect.priority_score.toFixed(2)}
                      </span>
                    </div>
                    <p className="mt-0.5 truncate text-xs text-slate-500">
                      {[prospect.category, prospect.address].filter(Boolean).join(" · ") || "—"}
                      {prospect.rating != null && ` · ★ ${prospect.rating} (${prospect.review_count})`}
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <Badge tone={research.tone}>{research.label}</Badge>
                    <Badge tone={outreach.tone}>{outreach.label}</Badge>

                    {prospect.research_status === "failed" && (
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<RefreshIcon width={14} height={14} />}
                        onClick={() => rerunResearch(prospect.id)}
                      >
                        Retry
                      </Button>
                    )}

                    <Button
                      variant={expanded ? "secondary" : "primary"}
                      size="sm"
                      onClick={() => openCallPanel(prospect)}
                      disabled={!ready}
                    >
                      Call
                    </Button>
                  </div>
                </div>

                {expanded && (
                  <div className="mt-4 border-t border-slate-100 pt-4">
                    {prospect.research.summary && (
                      <div className="mb-4 rounded-lg bg-slate-50/70 p-3">
                        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                          Knowledge base
                        </p>
                        <p className="text-sm text-slate-700">{prospect.research.summary}</p>
                        {prospect.research.hooks.length > 0 && (
                          <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-slate-500">
                            {prospect.research.hooks.map((h) => (
                              <li key={h}>{h}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}

                    <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                      <div className="flex-1">
                        <label className="mb-1.5 block text-sm font-medium text-slate-700">
                          Call with agent
                        </label>
                        <select
                          value={callAgentId}
                          onChange={(e) => setCallAgentId(e.target.value)}
                          className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-brand-300 focus:outline-none"
                        >
                          {retellAgents.length === 0 && <option value="">No Retell agents yet</option>}
                          {retellAgents.map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.name}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="flex-1">
                        <label className="mb-1.5 block text-sm font-medium text-slate-700">
                          Phone number
                        </label>
                        <TextInput
                          value={callNumber}
                          onChange={(e) => setCallNumber(e.target.value)}
                          placeholder="+491701234567"
                        />
                      </div>
                      <Button
                        onClick={() => placeCall(prospect)}
                        disabled={callingId === prospect.id || !callAgentId || !callNumber}
                      >
                        {callingId === prospect.id ? "Calling…" : "Place call"}
                      </Button>
                    </div>

                    {callFeedback[prospect.id] && (
                      <p className="mt-2 text-xs text-slate-500">{callFeedback[prospect.id]}</p>
                    )}

                    <div className="mt-3 flex gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setOutreach(prospect.id, "callback")}
                      >
                        Mark callback
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setOutreach(prospect.id, "do_not_call")}
                      >
                        Do not call
                      </Button>
                    </div>
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
