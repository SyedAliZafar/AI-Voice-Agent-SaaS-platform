"use client";

import { useEffect, useState } from "react";

import { DynamicVariableFields } from "@/components/features/agents/DynamicVariableFields";
import { CloseIcon } from "@/components/icons";
import { Badge, Button, Select, TextInput } from "@/components/ui";
import { useBatchRun } from "@/hooks/useBatchRun";
import { usePlatformAgents, usePlatformAgentVariables } from "@/hooks/usePlatformAgents";
import {
  isOptionalProspectVariable,
  isPerProspectVariable,
  suggestProspectVariables,
} from "@/lib/dynamicVariables";
import { Agent, BatchRunItemStatus, Prospect } from "@/lib/types";

/** Same idea as ProspectDetailPanel's picker: a local agent and a platform agent
 * (ADR-012) are not interchangeable, so the <select> value carries which kind it is. */
const PLATFORM_PREFIX = "platform:";

const ITEM_STATUS_META: Record<
  BatchRunItemStatus,
  { label: string; tone: "neutral" | "info" | "success" | "warning" }
> = {
  queued: { label: "Queued", tone: "neutral" },
  dialing: { label: "Dialing…", tone: "info" },
  done: { label: "Done", tone: "success" },
  skipped: { label: "Skipped", tone: "warning" },
};

/**
 * Header action + slide-over panel for a serial batch run: dial a small list of
 * prospects one at a time, waiting for each call to genuinely end (its real terminal
 * webhook, not a fixed interval) before the next goes out — see
 * phases/in-progress/serial-batch-calling.md.
 *
 * Two ways to say who to call. Tick rows in the list and this calls exactly those, in
 * that order; tick nothing and the count/city filters pick targets the way
 * POST /batch-call always has.
 */
export function BatchRunButton({
  agents,
  cityOptions,
  selectedProspects,
  onClearSelection,
  onChanged,
}: {
  agents: Agent[];
  cityOptions: string[];
  selectedProspects: Prospect[];
  onClearSelection: () => void;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [agentChoice, setAgentChoice] = useState(agents[0]?.id || "");
  const [limit, setLimit] = useState(5);
  const [city, setCity] = useState("");
  const [varValues, setVarValues] = useState<Record<string, string>>({});

  const { agents: platformAgents } = usePlatformAgents();
  const usingPlatformAgent = agentChoice.startsWith(PLATFORM_PREFIX);
  const selectedExternalId = usingPlatformAgent ? agentChoice.slice(PLATFORM_PREFIX.length) : null;
  const { variables } = usePlatformAgentVariables(selectedExternalId);

  const { run, starting, error, start, cancel, reset } = useBatchRun();

  const hasSelection = selectedProspects.length > 0;

  // {{company_name}} and friends are filled from each prospect by the backend at dial
  // time (batch_service._variables_for), so asking for them here would be asking for a
  // value that's right for at most one company in the batch. Only what's genuinely
  // batch-wide gets an input.
  const perProspectVars = variables.filter(isPerProspectVariable);
  const batchWideVars = variables.filter((v) => !isPerProspectVariable(v));
  const missingVars = batchWideVars.filter(
    (v) => !varValues[v]?.trim() && !isOptionalProspectVariable(v),
  );

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Once the run finishes, done/skipped items mean outreach counters moved under the
  // list behind this panel — refetch so it reflects that without a manual reload.
  useEffect(() => {
    if (run && run.status !== "running") onChanged();
  }, [run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  function close() {
    setOpen(false);
    reset();
  }

  async function handleStart() {
    if (!agentChoice) return;
    await start({
      ...(usingPlatformAgent
        ? { external_agent_id: selectedExternalId!, dynamic_variables: varValues }
        : { agent_id: agentChoice }),
      ...(hasSelection
        ? { prospect_ids: selectedProspects.map((p) => p.id) }
        : { limit, city: city || undefined }),
    });
  }

  return (
    <>
      <Button variant={hasSelection ? "primary" : "secondary"} size="sm" onClick={() => setOpen(true)}>
        {hasSelection ? `Batch call (${selectedProspects.length})` : "Batch call"}
      </Button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-30 bg-slate-900/20 backdrop-blur-[1px]"
            onClick={close}
            aria-hidden
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Batch call"
            className="animate-fade-in fixed inset-y-0 right-0 z-40 flex w-full max-w-lg flex-col border-l border-slate-200 bg-white shadow-2xl"
          >
            <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div>
                <p className="text-base font-semibold text-slate-900">Batch call</p>
                <p className="mt-0.5 text-xs text-slate-500">
                  Dials one prospect at a time — the next call only goes out once the
                  previous one genuinely ends.
                </p>
              </div>
              <button
                onClick={close}
                aria-label="Close"
                className="shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
              >
                <CloseIcon width={18} height={18} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4">
              {!run ? (
                <div className="space-y-4">
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-slate-700">
                      Call with agent
                    </label>
                    <Select value={agentChoice} onChange={(e) => setAgentChoice(e.target.value)}>
                      <option value="" disabled>
                        {agents.length === 0 && platformAgents.length === 0
                          ? "No agents yet"
                          : "Choose an agent…"}
                      </option>
                      {agents.length > 0 && (
                        <optgroup label="Your agents — personalized per prospect">
                          {agents.map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.name}
                            </option>
                          ))}
                        </optgroup>
                      )}
                      {platformAgents.length > 0 && (
                        <optgroup label="Retell dashboard agents — generic script">
                          {platformAgents.map((a) => (
                            <option key={a.external_id} value={`${PLATFORM_PREFIX}${a.external_id}`}>
                              {a.name}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </Select>
                    {!usingPlatformAgent && (
                      <p className="mt-1.5 text-xs text-slate-400">
                        Only prospects with research marked &quot;KB ready&quot; are eligible on
                        this path — anyone else is skipped, not failed.
                      </p>
                    )}
                  </div>

                  {hasSelection ? (
                    <div className="rounded-lg border border-brand-100 bg-brand-50/50 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium text-slate-800">
                          Calling {selectedProspects.length} selected{" "}
                          {selectedProspects.length === 1 ? "prospect" : "prospects"}
                        </p>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            onClearSelection();
                            setOpen(false);
                          }}
                        >
                          Clear
                        </Button>
                      </div>
                      <ol className="mt-2 space-y-0.5 text-xs text-slate-600">
                        {selectedProspects.map((p, i) => (
                          <li key={p.id} className="truncate tabular-nums">
                            {i + 1}. {p.name}
                            {!p.phone && <span className="text-amber-600"> — no phone number</span>}
                          </li>
                        ))}
                      </ol>
                      <p className="mt-2 text-xs text-slate-400">
                        Called in this order, top to bottom.
                      </p>
                    </div>
                  ) : (
                    <>
                      <div className="flex gap-3">
                        <div className="flex-1">
                          <label className="mb-1.5 block text-sm font-medium text-slate-700">
                            How many
                          </label>
                          <TextInput
                            type="number"
                            min={1}
                            max={15}
                            value={limit}
                            onChange={(e) =>
                              setLimit(Math.max(1, Math.min(15, Number(e.target.value) || 1)))
                            }
                          />
                        </div>
                        <div className="flex-1">
                          <label className="mb-1.5 block text-sm font-medium text-slate-700">
                            City <span className="font-normal text-slate-400">(optional)</span>
                          </label>
                          <Select value={city} onChange={(e) => setCity(e.target.value)}>
                            <option value="">Any city</option>
                            {cityOptions.map((c) => (
                              <option key={c} value={c}>
                                {c}
                              </option>
                            ))}
                          </Select>
                        </div>
                      </div>
                      <p className="-mt-1 text-xs text-slate-400">
                        Picks the highest-priority prospects nobody has called yet. To choose
                        exactly who gets called, tick them in the list instead.
                      </p>
                    </>
                  )}

                  {usingPlatformAgent && (
                    <>
                      <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
                        This agent runs the script in your Retell dashboard — the knowledge base
                        and your notes are <strong>not</strong> sent, only the variables it
                        declares.
                      </p>

                      {perProspectVars.length > 0 && (
                        <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-3">
                          <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">
                            ✓ Already handled — nothing to type
                          </p>
                          <p className="mt-1 text-xs text-slate-600">
                            {hasSelection
                              ? "Each call fills these from the prospect it's dialing. Here's exactly what each one will use:"
                              : "Each call fills these from the prospect it's dialing, so there's no single value to enter."}
                          </p>

                          {hasSelection ? (
                            <div className="mt-2.5 space-y-2.5">
                              {perProspectVars.map((name) => (
                                <div key={name}>
                                  <p className="font-mono text-xs text-slate-500">{`{{${name}}}`}</p>
                                  <ul className="mt-1 space-y-0.5">
                                    {selectedProspects.slice(0, 4).map((p, i) => {
                                      const value = suggestProspectVariables([name], p)[name];
                                      return (
                                        <li key={p.id} className="truncate text-xs text-slate-500">
                                          <span className="tabular-nums text-slate-400">
                                            Call {i + 1}:{" "}
                                          </span>
                                          {value ? (
                                            <span className="font-medium text-slate-800">
                                              {value}
                                            </span>
                                          ) : (
                                            <span className="text-amber-700">
                                              nothing on file — this one gets skipped
                                            </span>
                                          )}
                                        </li>
                                      );
                                    })}
                                    {selectedProspects.length > 4 && (
                                      <li className="text-xs text-slate-400">
                                        …and {selectedProspects.length - 4} more, each with its own
                                      </li>
                                    )}
                                  </ul>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {perProspectVars.map((name) => (
                                <span
                                  key={name}
                                  className="rounded bg-white px-2 py-0.5 font-mono text-xs text-slate-600 ring-1 ring-slate-200"
                                >
                                  {`{{${name}}}`}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      <DynamicVariableFields
                        variables={batchWideVars}
                        values={varValues}
                        optionalVariables={batchWideVars.filter(isOptionalProspectVariable)}
                        onChange={(name, value) =>
                          setVarValues((v) => ({ ...v, [name]: value }))
                        }
                      />
                    </>
                  )}

                  {error && <p className="text-xs text-red-600">{error}</p>}

                  <Button
                    onClick={handleStart}
                    disabled={starting || !agentChoice || missingVars.length > 0}
                    className="w-full"
                  >
                    {starting
                      ? "Starting…"
                      : hasSelection
                        ? `Call ${selectedProspects.length} selected`
                        : `Start batch of ${limit}`}
                  </Button>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <Badge
                        tone={
                          run.status === "running"
                            ? "info"
                            : run.status === "done"
                              ? "success"
                              : run.status === "cancelled"
                                ? "neutral"
                                : "danger"
                        }
                      >
                        {run.status === "running" ? "Running…" : run.status}
                      </Badge>
                      <span className="ml-2 text-xs text-slate-500">
                        {
                          run.items.filter((i) => i.status === "done" || i.status === "skipped")
                            .length
                        }{" "}
                        of {run.total} worked
                      </span>
                    </div>
                    {run.status === "running" && (
                      <Button variant="secondary" size="sm" onClick={cancel}>
                        Cancel
                      </Button>
                    )}
                  </div>

                  <ul className="space-y-2">
                    {run.items.map((item) => {
                      const meta = ITEM_STATUS_META[item.status];
                      return (
                        <li
                          key={item.prospect_id}
                          className="flex items-center justify-between gap-2 rounded-lg border border-slate-100 px-3 py-2"
                        >
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium text-slate-800">
                              {item.name}
                            </p>
                            {item.skip_reason && (
                              <p className="truncate text-xs text-slate-400">{item.skip_reason}</p>
                            )}
                          </div>
                          <Badge tone={meta.tone}>{meta.label}</Badge>
                        </li>
                      );
                    })}
                  </ul>

                  {run.status !== "running" && (
                    <Button variant="secondary" onClick={reset} className="w-full">
                      Start another batch
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}
