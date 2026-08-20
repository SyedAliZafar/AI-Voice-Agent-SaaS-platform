"use client";

import { useRouter } from "next/navigation";

import { SandboxChat } from "@/components/features/prospects/SandboxChat";
import { SandboxContextPanel } from "@/components/features/prospects/SandboxContextPanel";
import { ArrowLeftIcon, SparkleIcon } from "@/components/icons";
import { Card, Skeleton } from "@/components/ui";
import { useProspectSandbox } from "@/hooks/useProspectSandbox";

/** Text-chat sandbox for one prospect's personalized script — the same [COMPANY BRIEF]
 * + [OPERATOR NOTES] injection /call uses, run through the stateless text-chat
 * mechanism instead of a real phone call. See CONTEXT.md ADR-006.
 *
 * Unlike the agent-level sandbox (/agents/[id]/sandbox), the prompt isn't editable
 * here: it's built server-side from the agent's script + this prospect's research +
 * notes, and that's the point — what you read here is what the real call would say.
 * Edit the notes on the /prospects row instead of here if you want to change it.
 */
export default function ProspectSandboxPage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const {
    prospect,
    agents,
    models,
    defaultModel,
    selectedAgentId,
    setSelectedAgentId,
    selectedModel,
    setSelectedModel,
    messages,
    sendMessage,
    reset,
    sending,
    error,
    lastSystemPrompt,
  } = useProspectSandbox(params.id);

  if (!prospect) {
    return (
      <div className="animate-fade-in">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="mt-6 h-96 w-full rounded-2xl" />
      </div>
    );
  }

  const researchReady = prospect.research_status === "ready";
  const canChat = researchReady && !!selectedAgentId;

  return (
    <div className="animate-fade-in">
      <button
        onClick={() => router.push("/prospects")}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800"
      >
        <ArrowLeftIcon width={16} height={16} /> Back to Prospects
      </button>

      <div className="mb-6 flex items-center gap-2">
        <SparkleIcon width={20} height={20} className="text-brand-600" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Sandbox — {prospect.name}
          </h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Hear how the call would go, over text — no phone call, no telephony spend.
          </p>
        </div>
      </div>

      {!researchReady && (
        <Card className="mb-6 border-amber-200 bg-amber-50 p-4">
          <p className="text-sm text-amber-800">
            This prospect&apos;s research is {prospect.research_status}, not ready — the sandbox
            needs it to build the personalized script.
          </p>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <SandboxChat
          messages={messages}
          sending={sending}
          error={error}
          canChat={canChat}
          onSend={sendMessage}
          onReset={reset}
        />

        <SandboxContextPanel
          prospect={prospect}
          agents={agents}
          models={models}
          defaultModel={defaultModel}
          selectedAgentId={selectedAgentId}
          onAgentChange={setSelectedAgentId}
          selectedModel={selectedModel}
          onModelChange={setSelectedModel}
          lastSystemPrompt={lastSystemPrompt}
        />
      </div>
    </div>
  );
}
