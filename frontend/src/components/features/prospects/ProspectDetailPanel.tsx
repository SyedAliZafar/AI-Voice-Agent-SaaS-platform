"use client";

import { useState } from "react";

import { Button, TextInput } from "@/components/ui";
import { api, getApiErrorMessage } from "@/lib/api";
import { Agent, Prospect } from "@/lib/types";

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
}: {
  prospect: Prospect;
  agents: Agent[];
  onChanged: () => void;
}) {
  const [notesDraft, setNotesDraft] = useState(prospect.prospect_notes || "");
  const [savingNotes, setSavingNotes] = useState(false);

  const [callAgentId, setCallAgentId] = useState(agents[0]?.id || "");
  const [callNumber, setCallNumber] = useState(prospect.phone || "");
  const [calling, setCalling] = useState(false);

  const [feedback, setFeedback] = useState("");

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
        agent_id: callAgentId,
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
    <div className="mt-4 border-t border-slate-100 pt-4">
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
            {agents.length === 0 && <option value="">No Retell agents yet</option>}
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
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
        <Button onClick={placeCall} disabled={calling || !callAgentId || !callNumber}>
          {calling ? "Calling…" : "Place call"}
        </Button>
      </div>

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
