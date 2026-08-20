"use client";

import { useState } from "react";

import { DynamicVariableFields } from "@/components/features/agents/DynamicVariableFields";
import { AgentsIcon, PhoneIcon, RefreshIcon } from "@/components/icons";
import { Badge, Button, EmptyState, Field, Skeleton, TextInput } from "@/components/ui";
import {
  callPlatformAgent,
  usePlatformAgents,
  usePlatformAgentVariables,
} from "@/hooks/usePlatformAgents";
import { PlatformAgent } from "@/lib/types";

/** What each response-engine kind means for a dial from here. "custom-llm" is called out
 * because it's the case where "just dial it" does something we can't explain: the agent
 * points at some websocket, which may or may not be ours. */
const ENGINE_META: Record<string, { label: string; tone: "brand" | "info" | "neutral" }> = {
  "retell-llm": { label: "Retell LLM", tone: "brand" },
  "custom-llm": { label: "Custom LLM", tone: "info" },
  "conversation-flow": { label: "Conversation flow", tone: "neutral" },
};

export function PlatformAgentList() {
  const { agents, loading, error, reload } = usePlatformAgents();
  const [openId, setOpenId] = useState<string | null>(null);

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="card p-5">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="mt-2 h-3 w-32" />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <EmptyState
        icon={<AgentsIcon />}
        title="Could not load agents from Retell"
        description={error}
        action={
          <Button variant="secondary" icon={<RefreshIcon width={16} height={16} />} onClick={reload}>
            Try again
          </Button>
        }
      />
    );
  }

  if (agents.length === 0) {
    return (
      <EmptyState
        icon={<AgentsIcon />}
        title="No agents on the connected Retell account"
        description="Create one in the Retell dashboard and it will show up here — this list is read live, so there is nothing to import."
        action={
          <Button variant="secondary" icon={<RefreshIcon width={16} height={16} />} onClick={reload}>
            Refresh
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">
          Read live from Retell. These agents keep their own prompt, voice and brain — this
          dashboard only places the call.
        </p>
        <Button
          variant="secondary"
          icon={<RefreshIcon width={16} height={16} />}
          onClick={reload}
        >
          Refresh
        </Button>
      </div>

      {agents.map((agent) => (
        <PlatformAgentRow
          key={agent.external_id}
          agent={agent}
          open={openId === agent.external_id}
          onToggle={() =>
            setOpenId(openId === agent.external_id ? null : agent.external_id)
          }
        />
      ))}
    </div>
  );
}

function PlatformAgentRow({
  agent,
  open,
  onToggle,
}: {
  agent: PlatformAgent;
  open: boolean;
  onToggle: () => void;
}) {
  const [toNumber, setToNumber] = useState("");
  const [dialing, setDialing] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [varValues, setVarValues] = useState<Record<string, string>>({});

  // Only fetched once the row is expanded — reading an agent's placeholders costs two
  // Retell calls, and a collapsed row has nothing to show.
  const { variables } = usePlatformAgentVariables(open ? agent.external_id : null);
  const missingVars = variables.filter((v) => !varValues[v]?.trim());

  const engine = agent.engine ? ENGINE_META[agent.engine] : undefined;

  async function dial() {
    setDialing(true);
    setError(null);
    setResult(null);
    try {
      const call = await callPlatformAgent(agent.external_id, toNumber, varValues);
      setResult(`Dialing ${toNumber} as “${call.agent_name}” from ${call.from_number}.`);
      setToNumber("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDialing(false);
    }
  }

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-semibold text-slate-900" title={agent.name}>
            {agent.name}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            {engine ? (
              <Badge tone={engine.tone}>{engine.label}</Badge>
            ) : agent.engine ? (
              <Badge>{agent.engine}</Badge>
            ) : null}
            {agent.voice_id && <Badge>{agent.voice_id}</Badge>}
          </div>
          <p className="mt-2 font-mono text-xs text-slate-400">{agent.external_id}</p>
        </div>
        <Button
          variant={open ? "secondary" : "primary"}
          icon={<PhoneIcon width={16} height={16} />}
          onClick={onToggle}
        >
          {open ? "Cancel" : "Call"}
        </Button>
      </div>

      {open && (
        <div className="mt-4 border-t border-slate-100 pt-4">
          <Field label="Number to dial" hint="E.164 format, e.g. +491701234567">
            <TextInput
              value={toNumber}
              onChange={(e) => setToNumber(e.target.value)}
              placeholder="+491701234567"
            />
          </Field>
          <DynamicVariableFields
            variables={variables}
            values={varValues}
            onChange={(name, value) => setVarValues((v) => ({ ...v, [name]: value }))}
          />

          <Button
            className="mt-4"
            onClick={dial}
            disabled={dialing || !toNumber.trim() || missingVars.length > 0}
          >
            {dialing ? "Dialing…" : "Place call"}
          </Button>
          {missingVars.length > 0 && (
            <p className="mt-2 text-xs text-amber-700">
              Fill {missingVars.map((v) => `{{${v}}}`).join(", ")} first — Retell speaks an
              empty placeholder out loud.
            </p>
          )}
          {result && <p className="mt-3 text-sm text-emerald-600">{result}</p>}
          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        </div>
      )}
    </div>
  );
}
