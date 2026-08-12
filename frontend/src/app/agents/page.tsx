"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { AgentCard } from "@/components/features/agents/AgentCard";
import { AgentCategoryTiles } from "@/components/features/agents/AgentCategoryTiles";
import { ArrowLeftIcon, AgentsIcon, PlusIcon } from "@/components/icons";
import { Button, EmptyState, PageHeader, Skeleton } from "@/components/ui";
import { parseAgentName, sortLabels } from "@/lib/agentGrouping";
import { api } from "@/lib/api";
import { Agent } from "@/lib/types";

/** useSearchParams() opts this whole tree out of static rendering unless wrapped in
 * Suspense — Next.js requires this at build time. The page has no server data (it's
 * fully client-fetched already), so the fallback below is never actually visible in
 * practice; it exists to satisfy the framework requirement, not to be seen. */
export default function AgentsPage() {
  return (
    <Suspense fallback={null}>
      <AgentsPageInner />
    </Suspense>
  );
}

function AgentsPageInner() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const industryFilter = searchParams.get("industry") || "";

  // Reflects the selected category into the URL (shareable, survives refresh) —
  // same pattern as ProspectsPage's setParam.
  function selectIndustry(value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set("industry", value);
    else params.delete("industry");
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  useEffect(() => {
    api
      .get<Agent[]>("/agents")
      .then((res) => setAgents(res.data))
      .catch(() => setAgents([]))
      .finally(() => setLoading(false));
  }, []);

  const categories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const agent of agents) {
      const { industry } = parseAgentName(agent.name);
      counts.set(industry, (counts.get(industry) || 0) + 1);
    }
    return sortLabels([...counts.keys()]).map((industry) => ({
      industry,
      count: counts.get(industry)!,
    }));
  }, [agents]);

  const filteredAgents = agents.filter(
    (agent) => parseAgentName(agent.name).industry === industryFilter,
  );

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Agents"
        subtitle="Configure and manage your AI voice agents."
        actions={
          <Button icon={<PlusIcon width={16} height={16} />} onClick={() => router.push("/agents/new")}>
            Create agent
          </Button>
        }
      />

      {loading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card p-5">
              <Skeleton className="h-10 w-10 rounded-xl" />
              <Skeleton className="mt-4 h-4 w-40" />
              <Skeleton className="mt-2 h-4 w-full" />
            </div>
          ))}
        </div>
      ) : agents.length === 0 ? (
        <EmptyState
          icon={<AgentsIcon />}
          title="No agents yet"
          description="Create your first voice agent to start handling calls."
          action={
            <Button icon={<PlusIcon width={16} height={16} />} onClick={() => router.push("/agents/new")}>
              Create agent
            </Button>
          }
        />
      ) : !industryFilter ? (
        <AgentCategoryTiles categories={categories} onSelect={selectIndustry} />
      ) : (
        <>
          <div className="mb-4 flex items-center gap-3">
            <button
              onClick={() => selectIndustry("")}
              className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800"
            >
              <ArrowLeftIcon width={16} height={16} /> All categories
            </button>
            <span className="text-sm text-slate-300">/</span>
            <span className="text-sm font-medium text-slate-700">{industryFilter}</span>
          </div>

          {filteredAgents.length === 0 ? (
            <EmptyState
              icon={<AgentsIcon />}
              title="No agents in this category"
              description="Pick a different category, or create one here."
              action={
                <Button variant="secondary" onClick={() => selectIndustry("")}>
                  All categories
                </Button>
              }
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {filteredAgents.map((agent) => (
                <AgentCard key={agent.id} agent={agent} onClick={() => router.push(`/agents/${agent.id}`)} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
