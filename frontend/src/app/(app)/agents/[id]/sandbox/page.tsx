"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { PromptEditor } from "@/components/features/agents/PromptEditor";
import { ArrowLeftIcon, MicIcon, RefreshIcon, SparkleIcon } from "@/components/icons";
import { Button, Card, Skeleton } from "@/components/ui";
import { useSpeechToText } from "@/hooks/useSpeechToText";
import { api, getApiErrorMessage } from "@/lib/api";
import { Agent, LlmModel, SandboxChatResponse, SandboxMessage } from "@/lib/types";

export default function AgentSandboxPage({ params }: { params: { id: string } }) {
  const [agent, setAgent] = useState<Agent | null>(null);
  const [models, setModels] = useState<LlmModel[]>([]);
  const [defaultModel, setDefaultModel] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [promptDraft, setPromptDraft] = useState("");
  const [toolsEnabled, setToolsEnabled] = useState(false);
  const [messages, setMessages] = useState<SandboxMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const scrollRef = useRef<HTMLDivElement>(null);
  const { isListening, isSupported, start, stop } = useSpeechToText(setInput);

  useEffect(() => {
    api.get<Agent>(`/agents/${params.id}`).then((res) => {
      setAgent(res.data);
      setPromptDraft(res.data.system_prompt);
      setSelectedModel(res.data.llm_model);
    });
    api
      .get<{ models: LlmModel[]; default: string }>("/agents/models")
      .then((res) => {
        setModels(res.data.models);
        setDefaultModel(res.data.default);
      })
      .catch(() => setModels([]));
  }, [params.id]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  if (!agent) {
    return (
      <div className="animate-fade-in">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="mt-6 h-96 w-full rounded-2xl" />
      </div>
    );
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || sending) return;

    const next = [...messages, { role: "user" as const, content: text }];
    setMessages(next);
    setInput("");
    setSending(true);
    setError(null);
    try {
      const res = await api.post<SandboxChatResponse>(`/agents/${agent!.id}/sandbox-chat`, {
        messages: next,
        system_prompt_override: promptDraft,
        model: selectedModel || null,
        tools_enabled: toolsEnabled,
      });
      setMessages([...next, { role: "assistant", content: res.data.reply }]);
    } catch (err) {
      setError(getApiErrorMessage(err, "The sandbox chat failed. Check the backend logs."));
      setMessages(next); // keep the caller's message even though the reply failed
    } finally {
      setSending(false);
    }
  }

  async function savePromptToAgent(value: string) {
    await api.patch(`/agents/${agent!.id}`, { system_prompt: value });
    setAgent({ ...agent!, system_prompt: value });
  }

  const activeModelId = selectedModel || defaultModel;
  const activeModelLabel = models.find((m) => m.id === activeModelId)?.label || activeModelId;

  return (
    <div className="animate-fade-in">
      <button
        onClick={() => router.push(`/agents/${agent.id}`)}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800"
      >
        <ArrowLeftIcon width={16} height={16} /> Back to {agent.name}
      </button>

      <div className="mb-6 flex items-center gap-2">
        <SparkleIcon width={20} height={20} className="text-brand-600" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Sandbox — {agent.name}
          </h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Try this agent&apos;s persona over text before spending a real call on it.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="flex h-[32rem] flex-col p-0 lg:col-span-2">
          <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-5">
            {messages.length === 0 ? (
              <p className="py-10 text-center text-sm text-slate-400">
                Say something to start the conversation.
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
          {error && <p className="border-t border-slate-100 px-5 py-2 text-xs text-red-600">{error}</p>}
          {isListening && (
            <p className="flex items-center gap-1.5 border-t border-slate-100 px-5 py-1.5 text-xs text-red-600">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />
              Listening…
            </p>
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
              placeholder="Type what the caller would say…"
              className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none"
            />
            <Button
              size="sm"
              variant="ghost"
              icon={<MicIcon width={14} height={14} className={isListening ? "animate-pulse" : undefined} />}
              onClick={() => (isListening ? stop() : start())}
              disabled={!isSupported || sending}
              title={isSupported ? "Speak your message" : "Speech input isn't supported in this browser"}
              className={isListening ? "bg-red-50 text-red-600 hover:bg-red-100" : undefined}
            />
            <Button size="sm" onClick={sendMessage} disabled={sending || !input.trim()}>
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
              title="Clear the conversation (keeps the prompt draft)"
            >
              Reset
            </Button>
          </div>
        </Card>

        <div className="space-y-6">
          <Card className="p-5">
            <p className="mb-3 text-sm font-semibold text-slate-900">Model</p>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              disabled={models.length === 0}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-300 focus:outline-none disabled:opacity-50"
            >
              <option value="">
                Agent default{defaultModel ? ` (${models.find((m) => m.id === defaultModel)?.label ?? defaultModel})` : ""}
              </option>
              {models.map((m) => (
                <option key={m.id} value={m.id} disabled={!m.configured}>
                  {m.label}
                  {!m.configured ? " (no API key configured)" : ""}
                </option>
              ))}
            </select>
            <p className="mt-2 text-xs text-slate-500">Currently answering as {activeModelLabel}.</p>

            <label className="mt-4 flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={toolsEnabled}
                onChange={(e) => setToolsEnabled(e.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-300"
              />
              Run server-side tools
            </label>
            {toolsEnabled && (
              <p className="mt-1.5 text-xs text-amber-600">
                Tool calls here are real — book_appointment and create_lead will hit Cal.com/HubSpot,
                not a mock.
              </p>
            )}
          </Card>

          <div>
            <p className="mb-2 text-sm font-semibold text-slate-900">System prompt</p>
            <PromptEditor
              initialValue={agent.system_prompt}
              onChange={setPromptDraft}
              onSave={savePromptToAgent}
            />
            <p className="mt-2 text-xs text-slate-500">
              Edits here are used for the next message you send, whether or not you&apos;ve saved
              them. &quot;Save prompt&quot; writes the draft back to the agent.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
