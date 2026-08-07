"use client";

import { useWebSocket } from "@/hooks/useWebSocket";

export function LiveCallPanel({ callId }: { callId: string }) {
  const events = useWebSocket(callId);

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
          </span>
          <p className="text-sm font-medium text-slate-900">
            Live · call{" "}
            <span className="font-mono text-slate-500">{callId.slice(0, 8)}</span>
          </p>
        </div>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 tabular-nums">
          {events.length} events
        </span>
      </div>

      <div className="max-h-96 space-y-2 overflow-y-auto p-4">
        {events.map((event, i) => (
          <div
            key={i}
            className="flex items-start gap-2 rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2"
          >
            <span className="mt-0.5 shrink-0 rounded-md bg-brand-50 px-1.5 py-0.5 text-[11px] font-medium text-brand-700">
              {event.type}
            </span>
            <code className="min-w-0 break-words text-xs text-slate-500">
              {JSON.stringify(event.payload)}
            </code>
          </div>
        ))}
        {events.length === 0 && (
          <div className="flex flex-col items-center py-10 text-center">
            <div className="mb-2 h-6 w-6 animate-spin rounded-full border-2 border-slate-200 border-t-brand-500" />
            <p className="text-sm text-slate-400">Waiting for call events…</p>
          </div>
        )}
      </div>
    </div>
  );
}
