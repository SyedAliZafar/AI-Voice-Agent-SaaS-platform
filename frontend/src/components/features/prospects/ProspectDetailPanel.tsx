"use client";

import { useEffect, useRef, useState } from "react";

import { DynamicVariableFields } from "@/components/features/agents/DynamicVariableFields";
import { Button, TextInput } from "@/components/ui";
import { usePlatformAgents, usePlatformAgentVariables } from "@/hooks/usePlatformAgents";
import { api, getApiErrorMessage } from "@/lib/api";
import { isOptionalProspectVariable, suggestProspectVariables } from "@/lib/dynamicVariables";
import { Agent, Prospect } from "@/lib/types";

/** The picker holds two kinds of agent that are NOT interchangeable, so the value
 * carries which kind it is rather than the caller guessing from the id's shape. A local
 * agent gets this prospect's brief and notes injected for the call; a platform-native
 * one (ADR-012) runs the script it was given in Retell's dashboard and receives none of
 * it. Prefixing is what lets one <select> hold both without an ambiguous id. */
const PLATFORM_PREFIX = "platform:";

/** The expanded per-prospect panel: knowledge base summary, the operator's own
 * notes (wired into both the sandbox and the real call context — script_service
 * injects both), and the call form. Notes/call/outreach mutations live here
 * rather than in a hook, since they're one-shot user actions, not data the page
 * needs to hold — onChanged() tells the parent to refetch the list.
 */
export function ProspectDetailPanel({
  prospect,
  agents,
  onChanged,
  bare = false,
}: {
  prospect: Prospect;
  agents: Agent[];
  onChanged: () => void;
  /** Drops the top border/margin used when this rendered inline below a row (see
   * ProspectCallDrawer, which supplies its own header/border as drawer chrome). */
  bare?: boolean;
}) {
  const [notesDraft, setNotesDraft] = useState(prospect.prospect_notes || "");
  const [savingNotes, setSavingNotes] = useState(false);

  // Default to a local agent only when it can actually be used; otherwise leave the
  // picker empty rather than preselecting an option that would 422 on submit.
  const [callAgentId, setCallAgentId] = useState(
    prospect.research_status === "ready" ? agents[0]?.id || "" : "",
  );
  const [callNumber, setCallNumber] = useState(prospect.phone || "");
  const [calling, setCalling] = useState(false);

  const [feedback, setFeedback] = useState("");

  // Live Retell roster (ADR-012). Its own loading/error state is deliberately not
  // blocking this panel: the personalized path is the primary one here and must stay
  // usable when the platform is unreachable.
  const { agents: platformAgents } = usePlatformAgents();
  const usingPlatformAgent = callAgentId.startsWith(PLATFORM_PREFIX);

  // Only the personalized path needs the [COMPANY BRIEF], so only it waits for research.
  // A platform agent brings its own script and can dial an un-researched prospect —
  // including a CSV import, which never reaches "ready" at all (ADR-006).
  const researchReady = prospect.research_status === "ready";

  // The platform agent's prompt placeholders, prefilled from this prospect. Suggestions
  // are seeded into editable state (not merged at submit) so what the operator reads is
  // exactly what gets sent.
  const selectedExternalId = usingPlatformAgent
    ? callAgentId.slice(PLATFORM_PREFIX.length)
    : null;
  const { variables } = usePlatformAgentVariables(selectedExternalId);
  const [varValues, setVarValues] = useState<Record<string, string>>({});

  // Seed once per (agent, prospect, placeholder-set) — keyed on stable STRINGS, never on
  // the `prospect` object's identity.
  //
  // This effect used to depend on `prospect` directly, which silently made the form
  // unusable: useProspects refetches the whole list every 4s while any row is still
  // researching (and a CSV-imported row never leaves "pending" at all, ADR-006), so the
  // parent handed this component a brand-new prospect object on every poll. The effect
  // re-ran and overwrote whatever the operator was halfway through typing — you could
  // not enter a contact name at all. The other fields here escaped it only because
  // useState(initial) ignores later prop changes.
  const seedKey = `${selectedExternalId ?? ""}|${prospect.id}|${variables.join(",")}`;
  const seededFor = useRef<string | null>(null);

  useEffect(() => {
    if (seededFor.current === seedKey) return;
    seededFor.current = seedKey;
    setVarValues(variables.length ? suggestProspectVariables(variables, prospect) : {});
  }, [seedKey, variables, prospect]);

  // Optional placeholders (the contact name — see dynamicVariables) never block the call.
  const optionalVars = variables.filter(isOptionalProspectVariable);
  const missingVars = variables.filter(
    (v) => !varValues[v]?.trim() && !isOptionalProspectVariable(v),
  );

  async function saveNotes() {
    setSavingNotes(true);
    try {
      await api.patch(`/prospects/${prospect.id}`, { prospect_notes: notesDraft || null });
      setFeedback("Notes saved.");
      onChanged();
    } catch (err) {
      setFeedback(getApiErrorMessage(err, "Failed to save notes."));
    } finally {
      setSavingNotes(false);
    }
  }

  async function placeCall() {
    if (!callAgentId || !callNumber) return;
    setCalling(true);
    try {
      const res = await api.post(`/prospects/${prospect.id}/call`, {
        ...(usingPlatformAgent
          ? { external_agent_id: selectedExternalId, dynamic_variables: varValues }
          : { agent_id: callAgentId }),
        to_number: callNumber,
      });
      setFeedback(`Dialing from ${res.data.from_number} · call ${res.data.call_id.slice(0, 12)}…`);
      onChanged();
    } catch (err) {
      setFeedback(getApiErrorMessage(err, "Failed to place call."));
    } finally {
      setCalling(false);
    }
  }

  async function setOutreach(outreach_status: string) {
    await api.patch(`/prospects/${prospect.id}`, { outreach_status });
    onChanged();
  }

  return (
    <div className={bare ? "" : "mt-4 border-t border-slate-100 pt-4"}>
      {prospect.call_count > 0 && (
        <p className="mb-3 text-xs text-slate-500">
          Called <span className="font-medium tabular-nums">{prospect.call_count}×</span>
          {prospect.last_called_at && (
            <>
              {" · last on "}
              <span className="tabular-nums">
                {new Date(prospect.last_called_at).toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </span>
            </>
          )}
        </p>
      )}

      {prospect.research.summary && (
        <div className="mb-4 rounded-lg bg-slate-50/70 p-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Knowledge base
          </p>
          <p className="text-sm text-slate-700">{prospect.research.summary}</p>
          {prospect.research.hooks.length > 0 && (
            <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-slate-500">
              {prospect.research.hooks.map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="mb-4">
        <label
          htmlFor={`notes-${prospect.id}`}
          className="mb-1.5 block text-sm font-medium text-slate-700"
        >
          Your notes
        </label>
        <textarea
          id={`notes-${prospect.id}`}
          value={notesDraft}
          onChange={(e) => setNotesDraft(e.target.value)}
          rows={3}
          placeholder="Anything the research missed — who answers the phone, when to call, what they said last time…"
          className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-brand-300 focus:outline-none"
        />
        <div className="mt-1.5 flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={saveNotes}
            disabled={savingNotes || notesDraft === (prospect.prospect_notes || "")}
          >
            {savingNotes ? "Saving…" : "Save notes"}
          </Button>
          <span className="text-xs text-slate-400">
            Spoken on the real call, and trusted over the knowledge base above.
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label className="mb-1.5 block text-sm font-medium text-slate-700">Call with agent</label>
          <select
            value={callAgentId}
            onChange={(e) => setCallAgentId(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-brand-300 focus:outline-none"
          >
            <option value="" disabled>
              {agents.length === 0 && platformAgents.length === 0
                ? "No agents yet"
                : "Choose an agent…"}
            </option>
            {agents.length > 0 && (
              <optgroup
                label={
                  researchReady
                    ? "Your agents — personalized with this prospect"
                    : `Your agents — unavailable, research is ${prospect.research_status}`
                }
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id} disabled={!researchReady}>
                    {a.name}
                  </option>
                ))}
              </optgroup>
            )}
            {platformAgents.length > 0 && (
              <optgroup label="Retell dashboard agents — generic script">
                {platformAgents.map((a) => (
                  <option
                    key={a.external_id}
                    value={`${PLATFORM_PREFIX}${a.external_id}`}
                  >
                    {a.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </div>
        <div className="flex-1">
          <label className="mb-1.5 block text-sm font-medium text-slate-700">Phone number</label>
          <TextInput
            value={callNumber}
            onChange={(e) => setCallNumber(e.target.value)}
            placeholder="+491701234567"
          />
        </div>
        <Button
          onClick={placeCall}
          disabled={calling || !callAgentId || !callNumber || missingVars.length > 0}
        >
          {calling ? "Calling…" : "Place call"}
        </Button>
      </div>

      {usingPlatformAgent && (
        <>
          <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
            This agent runs the script in your Retell dashboard. The knowledge base and
            notes above are <strong>not</strong> sent — only the variables below, which its
            script has room for. Pick one of your own agents for a fully personalized call.
          </p>
          <DynamicVariableFields
            variables={variables}
            values={varValues}
            optionalVariables={optionalVars}
            onChange={(name, value) => setVarValues((v) => ({ ...v, [name]: value }))}
          />
          {missingVars.length > 0 && (
            <p className="mt-2 text-xs text-amber-700">
              Fill {missingVars.map((v) => `{{${v}}}`).join(", ")} before calling.
            </p>
          )}
        </>
      )}

      {feedback && <p className="mt-2 text-xs text-slate-500">{feedback}</p>}

      <div className="mt-3 flex gap-2">
        <Button variant="ghost" size="sm" onClick={() => setOutreach("callback")}>
          Mark callback
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setOutreach("do_not_call")}>
          Do not call
        </Button>
      </div>
    </div>
  );
}
