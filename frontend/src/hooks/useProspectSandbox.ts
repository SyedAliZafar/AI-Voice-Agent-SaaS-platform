import { useEffect, useState } from "react";

import { useAgents } from "@/hooks/useAgents";
import { useLlmModels } from "@/hooks/useLlmModels";
import { api, getApiErrorMessage } from "@/lib/api";
import { Prospect, SandboxChatResponse, SandboxMessage } from "@/lib/types";

/** Owns everything the prospect sandbox page needs: the prospect itself, the
 * agent/model pickers (via useAgents/useLlmModels), and the stateless chat turn —
 * the client resends the whole message history each turn, the same shape a live
 * call already uses (see sandbox_service.chat's docstring).
 */
export function useProspectSandbox(prospectId: string) {
  const [prospect, setProspect] = useState<Prospect | null>(null);
  const { agents } = useAgents();
  const { models, defaultModel } = useLlmModels();

  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [messages, setMessages] = useState<SandboxMessage[]>([]);
  const [lastSystemPrompt, setLastSystemPrompt] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Prospect>(`/prospects/${prospectId}`).then((res) => setProspect(res.data));
  }, [prospectId]);

  // Default the model dropdown to whichever agent gets picked, once one is —
  // mirrors the agent-level sandbox defaulting to that agent's own configured model.
  useEffect(() => {
    const agent = agents.find((a) => a.id === selectedAgentId);
    if (agent) setSelectedModel(agent.llm_model);
  }, [selectedAgentId, agents]);

  async function sendMessage(text: string) {
    if (!text || sending || !selectedAgentId) return;

    const next = [...messages, { role: "user" as const, content: text }];
    setMessages(next);
    setSending(true);
    setError(null);
    try {
      const res = await api.post<SandboxChatResponse>(`/prospects/${prospectId}/sandbox-chat`, {
        agent_id: selectedAgentId,
        messages: next,
        model: selectedModel || null,
      });
      setMessages([...next, { role: "assistant", content: res.data.reply }]);
      setLastSystemPrompt(res.data.system_prompt);
    } catch (err) {
      setError(getApiErrorMessage(err, "The sandbox chat failed. Check the backend logs."));
      setMessages(next); // keep the caller's message even though the reply failed
    } finally {
      setSending(false);
    }
  }

  function reset() {
    setMessages([]);
    setError(null);
  }

  return {
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
  };
}
