"use client";

import { Card } from "@/components/ui";
import { Agent, LlmModel, Prospect } from "@/lib/types";

/** Agent/model pickers plus "what's injected" — the KB summary and operator notes
 * the real call would use, and (once a turn has run) the exact assembled
 * system_prompt the backend just answered against. Showing the literal prompt
 * rather than a client-side reconstruction of it is the strongest proof that the
 * sandbox says what the real call would say.
 */
export function SandboxContextPanel({
  prospect,
  agents,
  models,
  defaultModel,
  selectedAgentId,
  onAgentChange,
  selectedModel,
  onModelChange,
  lastSystemPrompt,
}: {
  prospect: Prospect;
  agents: Agent[];
  models: LlmModel[];
  defaultModel: string;
  selectedAgentId: string;
  onAgentChange: (id: string) => void;
  selectedModel: string;
  onModelChange: (id: string) => void;
  lastSystemPrompt: string | null;
}) {
  const activeModelId = selectedModel || defaultModel;
  const activeModelLabel = models.find((m) => m.id === activeModelId)?.label || activeModelId;

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <p className="mb-3 text-sm font-semibold text-slate-900">Agent</p>
        <select
          value={selectedAgentId}
          onChange={(e) => onAgentChange(e.target.value)}
          disabled={agents.length === 0}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-300 focus:outline-none disabled:opacity-50"
        >
          <option value="">{agents.length === 0 ? "No agents yet" : "Choose an agent…"}</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>

        <p className="mb-3 mt-4 text-sm font-semibold text-slate-900">Model</p>
        <select
          value={selectedModel}
          onChange={(e) => onModelChange(e.target.value)}
          disabled={models.length === 0}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-brand-300 focus:outline-none disabled:opacity-50"
        >
          <option value="">
            Agent default
            {defaultModel ? ` (${models.find((m) => m.id === defaultModel)?.label ?? defaultModel})` : ""}
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
            Same brief and notes the real call would use — edit them from the /prospects row,
            not here.
          </p>
        </Card>
      )}

      {lastSystemPrompt && (
        <Card className="p-5">
          <details>
            <summary className="cursor-pointer text-sm font-semibold text-slate-900">
              Full prompt sent last turn
            </summary>
            <p className="mt-2 text-xs text-slate-400">
              The exact system prompt the reply above was generated from — the same one a real
              call to this prospect would use.
            </p>
            <pre className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
              {lastSystemPrompt}
            </pre>
          </details>
        </Card>
      )}
    </div>
  );
}
