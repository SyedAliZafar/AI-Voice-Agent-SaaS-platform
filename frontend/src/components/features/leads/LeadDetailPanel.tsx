"use client";

import { useState } from "react";

import { Button, Select, TextArea } from "@/components/ui";
import { api, getApiErrorMessage } from "@/lib/api";
import { Agent, Lead } from "@/lib/types";

/** The expanded per-lead panel: what came in with the lead, the operator's own notes
 * (the per-lead "holder" — injected into the call prompt alongside everything else,
 * see script_service.build_lead_prompt), which agent calls this lead, and the
 * scheduler's own state (attempts so far, next scheduled time, last outcome).
 */
export function LeadDetailPanel({
  lead,
  agents,
  onChanged,
}: {
  lead: Lead;
  agents: Agent[];
  onChanged: () => void;
}) {
  const [notesDraft, setNotesDraft] = useState(lead.notes || "");
  const [savingNotes, setSavingNotes] = useState(false);
  const [agentId, setAgentId] = useState(lead.agent_id || "");
  const [savingAgent, setSavingAgent] = useState(false);
  const [calling, setCalling] = useState(false);
  const [feedback, setFeedback] = useState("");

  async function saveNotes() {
    setSavingNotes(true);
    try {
      await api.patch(`/leads/${lead.id}`, { notes: notesDraft || null });
      setFeedback("Notes saved.");
      onChanged();
    } catch (err) {
      setFeedback(getApiErrorMessage(err, "Failed to save notes."));
    } finally {
      setSavingNotes(false);
    }
  }

  async function saveAgent(id: string) {
    setAgentId(id);
    setSavingAgent(true);
    try {
      await api.patch(`/leads/${lead.id}`, { agent_id: id || null });
      onChanged();
    } catch (err) {
      setFeedback(getApiErrorMessage(err, "Failed to set agent."));
    } finally {
      setSavingAgent(false);
    }
  }

  async function callNow() {
    setCalling(true);
    try {
      const res = await api.post(`/leads/${lead.id}/call`, {});
      setFeedback(`Dialing from ${res.data.from_number} · call ${res.data.call_id.slice(0, 12)}…`);
      onChanged();
    } catch (err) {
      setFeedback(getApiErrorMessage(err, "Failed to place call."));
    } finally {
      setCalling(false);
    }
  }

  const detailLines = [
    lead.service_requested && `Service requested: ${lead.service_requested}`,
    lead.budget && `Budget: ${lead.budget}`,
    [lead.city, lead.country].filter(Boolean).join(", ") &&
      `Location: ${[lead.city, lead.country].filter(Boolean).join(", ")}`,
    lead.email && `Email: ${lead.email}`,
  ].filter(Boolean) as string[];

  return (
    <div className="mt-4 border-t border-slate-100 pt-4">
      {(detailLines.length > 0 || lead.request_text) && (
        <div className="mb-4 rounded-lg bg-slate-50/70 p-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            What came in
          </p>
          {detailLines.map((line) => (
            <p key={line} className="text-sm text-slate-700">
              {line}
            </p>
          ))}
          {lead.request_text && (
            <p className="mt-1 text-sm italic text-slate-600">&ldquo;{lead.request_text}&rdquo;</p>
          )}
        </div>
      )}

      <div className="mb-4 grid gap-3 text-xs text-slate-500 sm:grid-cols-4">
        <div>
          <p className="font-semibold uppercase tracking-wide text-slate-400">Attempts</p>
          <p className="mt-0.5 text-slate-700">
            {lead.attempt_count} {lead.attempt_count === 1 ? "call" : "calls"}
          </p>
        </div>
        <div>
          <p className="font-semibold uppercase tracking-wide text-slate-400">Next attempt</p>
          <p className="mt-0.5 text-slate-700">
            {lead.next_attempt_at ? new Date(lead.next_attempt_at).toLocaleString() : "—"}
          </p>
        </div>
        <div>
          <p className="font-semibold uppercase tracking-wide text-slate-400">Last outcome</p>
          <p className="mt-0.5 text-slate-700">{lead.last_outcome || "—"}</p>
        </div>
        <div>
          <p className="font-semibold uppercase tracking-wide text-slate-400">Timezone</p>
          <p className="mt-0.5 text-slate-700">{lead.timezone || "default"}</p>
        </div>
      </div>

      <div className="mb-4">
        <label
          htmlFor={`lead-notes-${lead.id}`}
          className="mb-1.5 block text-sm font-medium text-slate-700"
        >
          Your notes
        </label>
        <TextArea
          id={`lead-notes-${lead.id}`}
          value={notesDraft}
          onChange={(e) => setNotesDraft(e.target.value)}
          rows={3}
          placeholder="Anything worth telling the agent before it calls…"
        />
        <div className="mt-1.5 flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={saveNotes}
            disabled={savingNotes || notesDraft === (lead.notes || "")}
          >
            {savingNotes ? "Saving…" : "Save notes"}
          </Button>
          <span className="text-xs text-slate-400">
            Spoken on the call, and trusted over everything else above.
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label className="mb-1.5 block text-sm font-medium text-slate-700">Call with agent</label>
          <Select
            value={agentId}
            onChange={(e) => saveAgent(e.target.value)}
            disabled={savingAgent}
          >
            <option value="">No agent assigned</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        </div>
        <Button onClick={callNow} disabled={calling || !agentId}>
          {calling ? "Calling…" : "Call now"}
        </Button>
      </div>

      {feedback && <p className="mt-2 text-xs text-slate-500">{feedback}</p>}
    </div>
  );
}
