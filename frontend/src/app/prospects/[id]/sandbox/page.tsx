"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ArrowLeftIcon, RefreshIcon, SparkleIcon } from "@/components/icons";
import { Button, Card, Skeleton } from "@/components/ui";
import { api, getApiErrorMessage } from "@/lib/api";
import { Agent, LlmModel, Prospect, SandboxChatResponse, SandboxMessage } from "@/lib/types";

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
  const [prospect, setProspect] = useState<Prospect | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [models, setModels] = useState<LlmModel[]>([]);
  const [defaultModel, setDefaultModel] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [messages, setMessages] = useState<SandboxMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.get<Prospect>(`/prospects/${params.id}`).then((res) => setProspect(res.data));
    // All platforms, not just Retell — this is text-only and has no telephony
    // dependency, unlike the real Call panel's agent picker.
    api
      .get<Agent[]>("/agents")
      .then((res) => setAgents(res.data))
      .catch(() => setAgents([]));
    api
      .get<{ models: LlmModel[]; default: string }>("/agents/models")
      .then((res) => {
        setModels(res.data.models);
        setDefaultModel(res.data.default);
      })
      .catch(() => setModels([]));
  }, [params.id]);

  // Default the model dropdown to whichever agent gets picked, once one is — mirrors
  // the agent-level sandbox defaulting to that agent's own configured model.
  useEffect(() => {
    const agent = agents.find((a) => a.id === selectedAgentId);
    if (agent) setSelectedModel(agent.llm_model);
  }, [selectedAgentId, agents]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  if (!prospect) {
    return (
      <div className="animate-fade-in">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="mt-6 h-96 w-full rounded-2xl" />
      </div>
    );
  }

  const researchReady = prospect.research_status === "ready";

  async function sendMessage() {
    const text = input.trim();
    if (!text || sending || !selectedAgentId) return;

    const next = [...messages, { role: "user" as const, content: text }];
    setMessages(next);
    setInput("");
    setSending(true);
    setError(null);
    try {
      const res = await api.post<SandboxChatResponse>(`/prospects/${prospect!.id}/sandbox-chat`, {
        agent_id: selectedAgentId,
        messages: next,
        model: selectedModel || null,
      });
      setMessages([...next, { role: "assistant", content: res.data.reply }]);
    } catch (err) {
      setError(getApiErrorMessage(err, "The sandbox chat failed. Check the backend logs."));
      setMessages(next); // keep the caller's message even though the reply failed
    } finally {
      setSending(false);
    }
  }

  const activeModelId = selectedModel || defaultModel;
  const activeModelLabel = models.find((m) => m.id === activeModelId)?.label || activeModelId;
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
            This prospect&apos;s research is {prospect.research_status}, not ready — the
            sandbox needs it to build the personalized script.
          </p>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="flex h-[32rem] flex-col p-0 lg:col-span-2">
          <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-5">
            {messages.length === 0 ? (
              <p className="py-10 text-center text-sm text-slate-400">
                {canChat
                  ? "Say something to start the conversation."
                  : "Pick an agent to start."}
              </p>
            ) : (
              messages.map((m, i) => (
                <div
                  key={i}
                  className={`flex ${m.role === "user" ? "justify-start" : "flex-row-reverse"}`}
                >
                  <div
                    className={`max-w-[80%] rounded-2xl px-3.5 py-2 text-sm ${
                      m.role === "user"
                        ? "rounded-tl-sm bg-slate-100 text-slate-800"
                        : "rounded-tr-sm bg-brand-600 text-white"
                    }`}
                  >
                    {m.content}
                  </div>
                </div>
              ))
            )}
            {sending && <p className="text-xs text-slate-400">Thinking…</p>}
          </div>
          {error && (
            <p className="border-t border-slate-100 px-5 py-2 text-xs text-red-600">{error}</p>
          )}
          <div className="flex items-center gap-2 border-t border-slate-100 p-3">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
              disabled={!canChat}
              placeholder={canChat ? "Type what the caller would say…" : "Pick an agent first…"}
              className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none disabled:opacity-50"
            />
            <Button size="sm" onClick={sendMessage} disabled={!canChat || sending || !input.trim()}>
              {sending ? "Sending…" : "Send"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              icon={<RefreshIcon width={14} height={14} />}
              onClick={() => {
                setMessages([]);
                setError(null);
              }}
              disabled={messages.length === 0 || sending}
              title="Clear the conversation"
            >
              Reset
            </Button>
          </div>
        </Card>

        <div className="space-y-6">
          <Card className="p-5">
            <p className="mb-3 text-sm font-semibold text-slate-900">Agent</p>
            <select
              value={selectedAgentId}
              onChange={(e) => setSelectedAgentId(e.target.value)}
              disabled={agents.length === 0}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-300 focus:outline-none disabled:opacity-50"
            >
              <option value="">
                {agents.length === 0 ? "No agents yet" : "Choose an agent…"}
              </option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>

            <p className="mb-3 mt-4 text-sm font-semibold text-slate-900">Model</p>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              disabled={models.length === 0}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-300 focus:outline-none disabled:opacity-50"
            >
              <option value="">
                Agent default
                {defaultModel
                  ? ` (${models.find((m) => m.id === defaultModel)?.label ?? defaultModel})`
                  : ""}
              </option>
              {models.map((m) => (
                <option key={m.id} value={m.id} disabled={!m.configured}>
                  {m.label}
                  {!m.configured ? " (no API key configured)" : ""}
                </option>
              ))}
            </select>
            {selectedAgentId && (
              <p className="mt-2 text-xs text-slate-500">Currently answering as {activeModelLabel}.</p>
            )}
          </Card>

          {(prospect.research.summary || prospect.prospect_notes) && (
            <Card className="p-5">
              <p className="mb-2 text-sm font-semibold text-slate-900">What&apos;s injected</p>
              {prospect.research.summary && (
                <>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                    Knowledge base
                  </p>
                  <p className="mt-1 text-sm text-slate-700">{prospect.research.summary}</p>
                </>
              )}
              {prospect.prospect_notes && (
                <>
                  <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
                    Your notes
                  </p>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">
                    {prospect.prospect_notes}
                  </p>
                </>
              )}
              <p className="mt-3 text-xs text-slate-400">
                Same brief and notes the real call would use — edit them from the
                /prospects row, not here.
              </p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
