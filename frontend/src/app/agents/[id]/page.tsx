"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { PromptEditor } from "@/components/PromptEditor";
import { ArrowLeftIcon, PhoneIcon, SparkleIcon } from "@/components/icons";
import { TextInput } from "@/components/form";
import { Badge, Button, Card, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { OBJECTIVE_LABELS, type CampaignIntake } from "@/lib/builder";
import { Agent } from "@/lib/types";

interface TestCallResult {
  call_id: string;
  from_number: string;
  status: string;
}

export default function AgentDetailPage({ params }: { params: { id: string } }) {
  const [agent, setAgent] = useState<Agent | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const [toNumber, setToNumber] = useState("");
  const [calling, setCalling] = useState(false);
  const [callResult, setCallResult] = useState<TestCallResult | null>(null);
  const [callError, setCallError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    api.get<Agent>(`/agents/${params.id}`).then((res) => setAgent(res.data)).catch(() => {});
  }, [params.id]);

  if (!agent) {
    return (
      <div className="animate-fade-in">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="mt-2 h-4 w-32" />
        <Skeleton className="mt-6 h-64 w-full rounded-2xl" />
      </div>
    );
  }

  const handleSave = async (system_prompt: string) => {
    await api.patch(`/agents/${agent.id}`, { system_prompt });
  };

  // Campaign intake is stashed under voice_config.campaign by the builder; keep it out of the
  // raw voice-settings list below.
  const voiceConfig = (agent.voice_config || {}) as Record<string, unknown>;
  const campaign = voiceConfig.campaign as CampaignIntake | undefined;
  const voiceEntries = Object.entries(voiceConfig).filter(([k]) => k !== "campaign");

  async function placeTestCall() {
    setCalling(true);
    setCallError(null);
    setCallResult(null);
    try {
      const res = await api.post<TestCallResult>(`/agents/${agent!.id}/test-call`, {
        to_number: toNumber,
      });
      setCallResult(res.data);
    } catch (err) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Failed to place call. Check the backend logs.";
      setCallError(message);
    } finally {
      setCalling(false);
    }
  }

  async function regeneratePrompt() {
    if (!campaign || !agent) return;
    setRegenerating(true);
    try {
      const res = await fetch("/api/strategist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "generate", intake: campaign }),
      });
      const data = await res.json();
      if (data.system_prompt) {
        await api.patch(`/agents/${agent.id}`, { system_prompt: data.system_prompt });
        setAgent({ ...agent, system_prompt: data.system_prompt });
      }
    } finally {
      setRegenerating(false);
    }
  }

  return (
    <div className="animate-fade-in">
      <button
        onClick={() => router.push("/agents")}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800"
      >
        <ArrowLeftIcon width={16} height={16} /> Back to agents
      </button>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-base font-semibold text-white">
          {agent.name.trim().charAt(0).toUpperCase() || "A"}
        </div>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{agent.name}</h1>
          <div className="mt-1 flex items-center gap-2 text-sm text-slate-500">
            <Badge tone="brand">{agent.platform}</Badge>
            <span>created {new Date(agent.created_at).toLocaleDateString()}</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <PromptEditor initialValue={agent.system_prompt} onSave={handleSave} />
        </div>

        <div className="space-y-6">
          <Card className="p-5">
            <div className="mb-3 flex items-center gap-2">
              <PhoneIcon width={16} height={16} className="text-brand-600" />
              <p className="text-sm font-semibold text-slate-900">Test call</p>
            </div>
            <p className="mb-3 text-xs text-slate-500">
              Dial your own phone to hear this agent&apos;s current script. Runs on Retell&apos;s
              built-in LLM — DeepSeek and server-side tools aren&apos;t exercised by this call.
            </p>
            <div className="flex gap-2">
              <TextInput
                value={toNumber}
                onChange={(e) => setToNumber(e.target.value)}
                placeholder="+491701234567"
                className="flex-1"
              />
              <Button
                size="sm"
                icon={<PhoneIcon width={14} height={14} />}
                onClick={placeTestCall}
                disabled={calling || !toNumber}
              >
                {calling ? "Calling…" : "Call me"}
              </Button>
            </div>
            {callResult && (
              <p className="mt-3 text-xs text-emerald-600">
                Dialing from {callResult.from_number} · call {callResult.call_id.slice(0, 12)}…
              </p>
            )}
            {callError && <p className="mt-3 text-xs text-red-600">{callError}</p>}
          </Card>

          {campaign && (
            <Card className="p-5">
              <div className="mb-3 flex items-center justify-between">
                <p className="text-sm font-semibold text-slate-900">Sales campaign</p>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<SparkleIcon width={14} height={14} />}
                  onClick={regeneratePrompt}
                  disabled={regenerating}
                >
                  {regenerating ? "…" : "Regenerate"}
                </Button>
              </div>
              <dl className="space-y-2.5 text-sm">
                <Row label="Target" value={campaign.target.company || "—"} />
                <Row label="Objective" value={OBJECTIVE_LABELS[campaign.goal.objective]} />
                <Row
                  label="Contact"
                  value={
                    campaign.target.contactName
                      ? `${campaign.target.contactName}${campaign.target.contactRole ? ` · ${campaign.target.contactRole}` : ""}`
                      : "—"
                  }
                />
                <Row label="Objections" value={`${campaign.pitch.objections.filter((o) => o.objection.trim()).length} scripted`} />
              </dl>
            </Card>
          )}

          <Card className="h-fit p-5">
            <p className="mb-3 text-sm font-semibold text-slate-900">Voice config</p>
            {voiceEntries.length === 0 ? (
              <p className="text-sm text-slate-400">No voice settings configured.</p>
            ) : (
              <dl className="space-y-2.5">
                {voiceEntries.map(([key, val]) => (
                  <Row key={key} label={key} value={String(val) || "—"} />
                ))}
              </dl>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className="truncate font-medium text-slate-800">{value}</dd>
    </div>
  );
}
