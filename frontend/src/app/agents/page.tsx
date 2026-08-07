"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { AgentCard } from "@/components/features/agents/AgentCard";
import { AgentsIcon, PlusIcon } from "@/components/icons";
import { Button, EmptyState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { Agent } from "@/lib/types";

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    api
      .get<Agent[]>("/agents")
      .then((res) => setAgents(res.data))
      .catch(() => setAgents([]))
      .finally(() => setLoading(false));
  }, []);

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
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {agents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} onClick={() => router.push(`/agents/${agent.id}`)} />
          ))}
        </div>
      )}
    </div>
  );
}
