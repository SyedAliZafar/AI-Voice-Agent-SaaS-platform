"use client";

import { useRouter } from "next/navigation";

import { AgentBuilder } from "@/components/features/agents/AgentBuilder";
import { ArrowLeftIcon } from "@/components/icons";

export default function NewAgentPage() {
  const router = useRouter();

  return (
    <div className="animate-fade-in">
      <button
        onClick={() => router.push("/agents")}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800"
      >
        <ArrowLeftIcon width={16} height={16} /> Back to agents
      </button>

      <h1 className="mb-1 text-2xl font-semibold tracking-tight text-slate-900">
        Build a sales agent
      </h1>
      <p className="mb-6 text-sm text-slate-500">
        Answer a few questions and the Strategist will write your outbound call playbook.
      </p>

      <AgentBuilder />
    </div>
  );
}
