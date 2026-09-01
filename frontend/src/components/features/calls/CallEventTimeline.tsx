"use client";

import { useState } from "react";

import { Badge } from "@/components/ui";
import { CallEvent } from "@/lib/types";

/**
 * What the agent actually did during a call, in order.
 *
 * These rows have been written on every custom-LLM call since ADR-009 and had no reader
 * until now — every investigation in phases/ got at them with hand-written SQL. The
 * point of this component is that the three things worth catching are visible at a
 * glance rather than reconstructed:
 *
 *  - a tool that was DISPATCHED but has no matching result (the call was cut off
 *    mid-side-effect — the exact scenario the shielded-execution work exists for),
 *  - a tool that errored, or came back "uncertain" (a timeout, which is NOT a confirmed
 *    failure and must not be read as one),
 *  - an ivr_hangup, which is otherwise indistinguishable from a prospect hanging up.
 *
 * Payloads are rendered by known keys where they exist and fall back to raw JSON
 * otherwise, deliberately: the writer owns those shapes, and a renderer that only
 * understands today's keys should degrade to showing everything, not to showing nothing.
 */

type Tone = "neutral" | "brand" | "success" | "warning" | "danger" | "info";

function toneFor(event: CallEvent): Tone {
  const phase = event.payload.phase;
  const status = (event.payload.result as { status?: string } | undefined)?.status;

  if (event.event_type === "ivr_hangup") return "warning";
  if (event.event_type === "llm_timing") return "neutral";
  if (phase === "error") return "danger";
  // "uncertain" is its own outcome on purpose — a request that timed out may well have
  // succeeded. Colouring it as an error would assert something the backend refused to.
  if (status === "uncertain") return "warning";
  if (phase === "result") return "success";
  return "info";
}

function labelFor(event: CallEvent): string {
  const tool = typeof event.payload.tool === "string" ? event.payload.tool : null;
  const phase = typeof event.payload.phase === "string" ? event.payload.phase : null;

  if (event.event_type === "tool_call" && tool) {
    return phase ? `${tool} · ${phase}` : tool;
  }
  if (event.event_type === "llm_timing") {
    const stage = typeof event.payload.stage === "string" ? event.payload.stage : "turn";
    return `LLM · ${stage}`;
  }
  if (event.event_type === "ivr_hangup") return "Phone menu detected — call ended";
  return event.event_type;
}

/** The one-line summary under each row: the numbers you'd actually scan for. */
function summaryFor(event: CallEvent): string | null {
  const p = event.payload;

  if (event.event_type === "llm_timing") {
    const parts: string[] = [];
    if (typeof p.ttfb_ms === "number") parts.push(`first word ${Math.round(p.ttfb_ms)}ms`);
    if (typeof p.duration_ms === "number") parts.push(`total ${Math.round(p.duration_ms)}ms`);
    if (typeof p.model === "string") parts.push(p.model);
    return parts.length ? parts.join(" · ") : null;
  }

  if (typeof p.error === "string") return p.error;

  const result = p.result as Record<string, unknown> | undefined;
  if (result && typeof result === "object") {
    if (typeof result.message === "string") return result.message;
    if (typeof result.status === "string") return `status: ${result.status}`;
  }
  return null;
}

function Row({ event }: { event: CallEvent }) {
  const [open, setOpen] = useState(false);
  const summary = summaryFor(event);
  const hasPayload = Object.keys(event.payload).length > 0;

  return (
    <li className="relative pl-6">
      <span className="absolute left-0 top-2 h-2 w-2 rounded-full bg-slate-300" />
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={toneFor(event)}>{labelFor(event)}</Badge>
        <span className="font-mono text-xs text-slate-400">
          {new Date(event.ts).toLocaleTimeString()}
        </span>
        {hasPayload && (
          <button
            onClick={() => setOpen((v) => !v)}
            className="text-xs text-slate-400 underline-offset-2 hover:text-slate-700 hover:underline"
          >
            {open ? "hide detail" : "detail"}
          </button>
        )}
      </div>

      {summary && <p className="mt-1 text-sm text-slate-600">{summary}</p>}

      {open && (
        <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
          {JSON.stringify(event.payload, null, 2)}
        </pre>
      )}
    </li>
  );
}

export function CallEventTimeline({
  events,
  loading,
  error,
}: {
  events: CallEvent[];
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return <p className="text-sm text-slate-400">Loading activity…</p>;
  }
  if (error) {
    return <p className="text-sm text-red-600">{error}</p>;
  }
  if (events.length === 0) {
    // Not an error, and worth saying why: a hosted-LLM call runs entirely on the
    // platform's side and never reaches the code that writes these rows.
    return (
      <p className="text-sm text-slate-500">
        No activity recorded. Calls answered by the voice platform&apos;s own LLM don&apos;t
        produce a trail — only calls running on this backend&apos;s conversation engine do.
      </p>
    );
  }

  const dispatched = events.filter(
    (e) => e.event_type === "tool_call" && e.payload.phase === "dispatched",
  ).length;
  const settled = events.filter(
    (e) => e.event_type === "tool_call" && e.payload.phase !== "dispatched",
  ).length;

  return (
    <div>
      {dispatched > settled && (
        // The case worth flagging loudly: something was sent to a third party and this
        // call has no record of how it turned out. It may well have succeeded — that is
        // precisely why it needs a human to check rather than being assumed either way.
        <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {dispatched - settled} tool call{dispatched - settled === 1 ? "" : "s"} started but
          never recorded a result. The action may still have gone through — check the
          provider before retrying it.
        </p>
      )}
      <ul className="space-y-4 border-l border-slate-200 pl-1">
        {events.map((e) => (
          <Row key={e.id} event={e} />
        ))}
      </ul>
    </div>
  );
}
