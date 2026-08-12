"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { AgentCard } from "@/components/features/agents/AgentCard";
import { AgentFilters } from "@/components/features/agents/AgentFilters";
import { AgentsIcon, PlusIcon } from "@/components/icons";
import { Button, EmptyState, PageHeader, Skeleton } from "@/components/ui";
import { agentOptions, parseAgentName } from "@/lib/agentGrouping";
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
  const serviceFilter = searchParams.get("service") || "";
  const styleFilter = searchParams.get("style") || "";

  // Reflects filters into the URL (shareable, survives refresh) rather than into
  // component state — same pattern as ProspectsPage's setParam.
  function setParam(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  function clearFilters() {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("industry");
    params.delete("service");
    params.delete("style");
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

  const industryOptions = useMemo(() => agentOptions(agents, "industry"), [agents]);
  const serviceOptions = useMemo(() => agentOptions(agents, "service"), [agents]);
  const styleOptions = useMemo(() => agentOptions(agents, "style"), [agents]);

  const filteredAgents = agents.filter((agent) => {
    const parsed = parseAgentName(agent.name);
    if (industryFilter && parsed.industry !== industryFilter) return false;
    if (serviceFilter && parsed.service !== serviceFilter) return false;
    if (styleFilter && parsed.style !== styleFilter) return false;
    return true;
  });

  const hasFilter = industryFilter || serviceFilter || styleFilter;

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
      ) : (
        <>
          <AgentFilters
            industry={industryFilter}
            service={serviceFilter}
            style={styleFilter}
            industryOptions={industryOptions}
            serviceOptions={serviceOptions}
            styleOptions={styleOptions}
            onIndustryChange={(v) => setParam("industry", v)}
            onServiceChange={(v) => setParam("service", v)}
            onStyleChange={(v) => setParam("style", v)}
            onClear={clearFilters}
          />

          {filteredAgents.length === 0 ? (
            <EmptyState
              icon={<AgentsIcon />}
              title="No agents match these filters"
              description="Try a different industry, service, or style, or clear the filters above."
              action={
                hasFilter ? (
                  <Button variant="secondary" onClick={clearFilters}>
                    Clear filters
                  </Button>
                ) : undefined
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
