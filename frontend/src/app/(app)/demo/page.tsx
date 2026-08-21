"use client";

import { useMemo, useState } from "react";

import { DynamicVariableFields } from "@/components/features/agents/DynamicVariableFields";
import { WebCallPanel } from "@/components/features/agents/WebCallPanel";
import { AgentsIcon } from "@/components/icons";
import { Badge, Card, EmptyState, Field, PageHeader, Select, Skeleton } from "@/components/ui";
import { useAgents } from "@/hooks/useAgents";
import {
  usePlatformAgentPrompt,
  usePlatformAgents,
  usePlatformAgentVariables,
} from "@/hooks/usePlatformAgents";
import { WebCallTarget } from "@/hooks/useWebCall";

/** Why a selected agent has no readable script, per response engine. Only retell-llm
 * keeps its prompt as one string we can fetch. */
const NO_PROMPT_REASON: Record<string, string> = {
  "custom-llm":
    "This agent answers over a Custom LLM websocket, so its prompt lives on whichever server handles that connection — not in Retell.",
  "conversation-flow":
    "This agent is a conversation flow. Its script is spread across flow nodes rather than a single prompt, so there is nothing to show here.",
};

/** One screen for running a client demo: pick any agent, see exactly what it will say,
 * and talk to it in the browser.
 *
 * Deliberately separate from /agents, which is for building and editing. The job here is
 * narrower and happens with someone watching — so it optimizes for picking fast and for
 * being able to answer "what does it actually know?" without leaving the page or opening
 * Retell's dashboard.
 */
export default function DemoPage() {
  const { agents: localAgents, loading: localLoading } = useAgents();
  const { agents: platformAgents, loading: platformLoading, error } = usePlatformAgents();
  const [selected, setSelected] = useState("");
  const [varValues, setVarValues] = useState<Record<string, string>>({});

  // "local:<uuid>" / "platform:<external_id>" — the two id spaces are different types on
  // the backend and can collide as bare strings, so the kind travels with the value.
  // Split on the FIRST colon only: an id may legitimately contain one.
  const sep = selected.indexOf(":");
  const kind = sep === -1 ? "" : selected.slice(0, sep);
  const id = sep === -1 ? "" : selected.slice(sep + 1);
  const isPlatform = kind === "platform";

  const platformAgent = platformAgents.find((a) => a.external_id === id);
  const localAgent = localAgents.find((a) => a.id === id);

  const { variables } = usePlatformAgentVariables(isPlatform ? id : null);
  const { prompt, loading: promptLoading } = usePlatformAgentPrompt(isPlatform ? id : null);

  const missingVars = variables.filter((v) => !varValues[v]?.trim());

  const target: WebCallTarget | null = useMemo(() => {
    if (!id) return null;
    return isPlatform
      ? { kind: "platform", externalAgentId: id, dynamicVariables: varValues }
      : { kind: "local", agentId: id };
  }, [id, isPlatform, varValues]);

  const loading = localLoading || platformLoading;

  // Local agents own their prompt in our database, so it's shown directly; platform
  // agents have to be fetched from Retell.
  const shownPrompt = isPlatform ? prompt?.general_prompt : localAgent?.system_prompt;
  const engine = isPlatform ? prompt?.engine : undefined;

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Demo"
        subtitle="Pick an agent, check what it knows, and talk to it — in the browser, no phone call."
      />

      {loading ? (
        <Skeleton className="h-24 w-full rounded-xl" />
      ) : localAgents.length === 0 && platformAgents.length === 0 ? (
        <EmptyState
          icon={<AgentsIcon />}
          title="No agents to demo yet"
          description={error || "Create an agent first, or build one in Retell's dashboard."}
        />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <Card className="p-5">
              <Field label="Agent" hint="Agents in this dashboard, plus everything on the Retell account.">
                <Select
                  value={selected}
                  onChange={(e) => {
                    setSelected(e.target.value);
                    // Placeholders belong to the agent that declared them — carrying
                    // values across a switch would silently feed one agent's script
                    // into another's.
                    setVarValues({});
                  }}
                >
                  <option value="">Select an agent…</option>
                  {localAgents.length > 0 && (
                    <optgroup label="Built here">
                      {localAgents.map((a) => (
                        <option key={a.id} value={`local:${a.id}`}>
                          {a.name}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {platformAgents.length > 0 && (
                    <optgroup label="On Retell">
                      {platformAgents.map((a) => (
                        <option key={a.external_id} value={`platform:${a.external_id}`}>
                          {a.name}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </Select>
              </Field>

              {id && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Badge tone={isPlatform ? "info" : "brand"}>
                    {isPlatform ? "Retell-native" : "Built here"}
                  </Badge>
                  {isPlatform && platformAgent?.voice_id && (
                    <Badge>{platformAgent.voice_id}</Badge>
                  )}
                  {isPlatform && prompt?.model && <Badge>{prompt.model}</Badge>}
                  {!isPlatform && localAgent?.use_custom_llm && (
                    <Badge tone="warning">Custom LLM — needs a live tunnel</Badge>
                  )}
                  <span className="font-mono text-xs text-slate-400">{id}</span>
                </div>
              )}

              {isPlatform && variables.length > 0 && (
                <DynamicVariableFields
                  variables={variables}
                  values={varValues}
                  onChange={(name, value) => setVarValues((v) => ({ ...v, [name]: value }))}
                />
              )}
            </Card>

            {id && (
              <Card className="p-5">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-slate-900">What this agent knows</p>
                  {shownPrompt && (
                    <span className="text-xs text-slate-400">
                      {shownPrompt.length.toLocaleString()} characters
                    </span>
                  )}
                </div>

                {promptLoading ? (
                  <Skeleton className="h-40 w-full rounded-lg" />
                ) : shownPrompt ? (
                  <>
                    {isPlatform && prompt?.begin_message && (
                      <div className="mb-3 rounded-lg border border-slate-200 bg-slate-50/60 p-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                          Opens with
                        </p>
                        <p className="mt-1 text-sm text-slate-700">{prompt.begin_message}</p>
                      </div>
                    )}
                    <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50/60 p-3 font-mono text-xs leading-relaxed text-slate-700">
                      {shownPrompt}
                    </pre>
                    {isPlatform && (
                      <p className="mt-2 text-xs text-slate-500">
                        Read live from Retell. Edit it there — this dashboard doesn&apos;t own
                        this agent&apos;s script.
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-slate-500">
                    {(engine && NO_PROMPT_REASON[engine]) ||
                      "This agent has no prompt text to show."}
                  </p>
                )}
              </Card>
            )}
          </div>

          <div className="lg:col-span-1">
            <WebCallPanel
              target={target}
              agentName={isPlatform ? platformAgent?.name : localAgent?.name}
              disabledReason={
                !id
                  ? "Select an agent to start."
                  : missingVars.length > 0
                    ? `Fill ${missingVars.map((v) => `{{${v}}}`).join(", ")} first — Retell speaks an empty placeholder out loud.`
                    : undefined
              }
            />
          </div>
        </div>
      )}
    </div>
  );
}
