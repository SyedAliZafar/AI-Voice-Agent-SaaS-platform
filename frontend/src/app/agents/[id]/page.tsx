"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { PromptEditor } from "@/components/PromptEditor";
import { ArrowLeftIcon, PhoneIcon, SparkleIcon } from "@/components/icons";
import { TextInput } from "@/components/form";
import { Badge, Button, Card, Skeleton } from "@/components/ui";
import { api, getApiErrorMessage } from "@/lib/api";
import { OBJECTIVE_LABELS, type CampaignIntake } from "@/lib/builder";
import { Agent, LlmModel } from "@/lib/types";

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
  const [savingBrain, setSavingBrain] = useState(false);
  const [models, setModels] = useState<LlmModel[]>([]);
  const [defaultModel, setDefaultModel] = useState("");
  const [savingModel, setSavingModel] = useState(false);
  const router = useRouter();

  useEffect(() => {
    api.get<Agent>(`/agents/${params.id}`).then((res) => setAgent(res.data)).catch(() => {});
    api
      .get<{ models: LlmModel[]; default: string }>("/agents/models")
      .then((res) => {
        setModels(res.data.models);
        setDefaultModel(res.data.default);
      })
      .catch(() => setModels([]));
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

  // The model actually in effect: the agent's own choice, or the backend's configured
  // default (empty llm_model means "use settings.default_llm_model").
  const effectiveModelId = agent.llm_model || defaultModel;
  const effectiveModelLabel =
    models.find((m) => m.id === effectiveModelId)?.label || effectiveModelId || "the configured model";

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
      setCallError(getApiErrorMessage(err, "Failed to place call. Check the backend logs."));
    } finally {
      setCalling(false);
    }
  }

  async function toggleCustomLlm(next: boolean) {
    if (!agent) return;
    setSavingBrain(true);
    setCallError(null);
    try {
      await api.patch(`/agents/${agent.id}`, { use_custom_llm: next });
      setAgent({ ...agent, use_custom_llm: next });
    } catch (err) {
      setCallError(getApiErrorMessage(err, "Couldn't change the conversation engine."));
    } finally {
      setSavingBrain(false);
    }
  }

  async function changeModel(next: string) {
    if (!agent) return;
    setSavingModel(true);
    setCallError(null);
    try {
      await api.patch(`/agents/${agent.id}`, { llm_model: next });
      setAgent({ ...agent, llm_model: next });
    } catch (err) {
      setCallError(getApiErrorMessage(err, "Couldn't change the model."));
    } finally {
      setSavingModel(false);
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

      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
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
        <Button
          variant="secondary"
          size="sm"
          icon={<SparkleIcon width={14} height={14} />}
          onClick={() => router.push(`/agents/${agent.id}/sandbox`)}
        >
          Try in sandbox
        </Button>
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
              {agent.use_custom_llm ? (
                <>
                  Dial your own phone to hear this agent&apos;s current script. Runs on{" "}
                  <strong className="font-medium text-slate-700">{effectiveModelLabel}</strong>{" "}
                  via your Custom LLM websocket, with server-side tools. Needs{" "}
                  <code>PUBLIC_BASE_URL</code> set and a tunnel running, or the call will fail.
                </>
              ) : (
                <>
                  Dial your own phone to hear this agent&apos;s current script. Runs on{" "}
                  <strong className="font-medium text-slate-700">Retell&apos;s built-in LLM</strong>{" "}
                  — {effectiveModelLabel} and server-side tools aren&apos;t exercised by this call.
                </>
              )}
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

          <Card className="p-5">
            <p className="mb-1 text-sm font-semibold text-slate-900">Conversation engine</p>
            <p className="mb-3 text-xs text-slate-500">
              Which brain answers the caller. Retell&apos;s hosted LLM needs no setup; a Custom
              LLM runs your own prompt logic and server-side tools, on whichever model you pick
              below.
            </p>
            <div className="space-y-2">
              <EngineOption
                selected={!agent.use_custom_llm}
                disabled={savingBrain}
                onSelect={() => toggleCustomLlm(false)}
                title="Retell built-in LLM"
                detail="Zero setup. No tunnel required."
              />
              <EngineOption
                selected={agent.use_custom_llm}
                disabled={savingBrain}
                onSelect={() => toggleCustomLlm(true)}
                title="Custom LLM"
                detail="Server-side tools. Needs PUBLIC_BASE_URL + tunnel."
              />
            </div>

            {agent.use_custom_llm && (
              <div className="mt-4 border-t border-slate-100 pt-4">
                <label className="mb-1.5 block text-xs font-medium text-slate-700">
                  Model
                </label>
                <select
                  value={agent.llm_model}
                  onChange={(e) => changeModel(e.target.value)}
                  disabled={savingModel || models.length === 0}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-300 focus:outline-none disabled:opacity-50"
                >
                  <option value="">
                    Default{defaultModel ? ` (${models.find((m) => m.id === defaultModel)?.label ?? defaultModel})` : ""}
                  </option>
                  {models.map((m) => (
                    <option key={m.id} value={m.id} disabled={!m.configured}>
                      {m.label}
                      {!m.configured ? " (no API key configured)" : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </Card>

          <Card className="h-fit p-5">
            <p className="mb-3 text-sm font-semibold text-slate-900">Voice config</p>
            {voiceEntries.length === 0 ? (
              <p className="text-sm text-slate-400">No voice settings configured.</p>
            ) : (
              <dl className="space-y-2.5">
                {voiceEntries.map(([key, val]) => (
                  <Row key={key} label={key} value={formatConfigValue(val)} />
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
      <dd className="truncate font-medium text-slate-800" title={value}>
        {value}
      </dd>
    </div>
  );
}

/** Voice config values are often nested objects (the cached `retell` / `retell_custom`
 *  provisioning ids). String(val) on those renders "[object Object]" — summarize instead. */
function formatConfigValue(val: unknown): string {
  if (val === null || val === undefined || val === "") return "—";
  if (typeof val === "object") {
    const entries = Object.entries(val as Record<string, unknown>)
      .filter(([, v]) => v !== null && v !== undefined && v !== "")
      .map(([k, v]) => `${k}: ${String(v)}`);
    return entries.length ? entries.join(" · ") : "—";
  }
  return String(val);
}

function EngineOption({
  selected,
  disabled,
  onSelect,
  title,
  detail,
}: {
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
  title: string;
  detail: string;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled || selected}
      aria-pressed={selected}
      className={`w-full rounded-lg border p-3 text-left transition-colors disabled:cursor-default ${
        selected
          ? "border-brand-300 bg-brand-50"
          : "border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-50"
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`h-3.5 w-3.5 shrink-0 rounded-full border-[3px] ${
            selected ? "border-brand-600 bg-white" : "border-slate-300 bg-white"
          }`}
        />
        <span className="text-sm font-medium text-slate-900">{title}</span>
      </div>
      <p className="mt-1 pl-[1.375rem] text-xs text-slate-500">{detail}</p>
    </button>
  );
}
