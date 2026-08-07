"use client";

import { useState } from "react";

import { LiveCallPanel } from "@/components/features/calls/LiveCallPanel";
import { LiveIcon } from "@/components/icons";
import { Button, Card, EmptyState, PageHeader } from "@/components/ui";

export default function LiveCallsPage() {
  const [callId, setCallId] = useState("");
  const [activeCallId, setActiveCallId] = useState<string | null>(null);

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Live call monitor"
        subtitle="Watch call events stream in real time over WebSocket."
      />

      <Card className="mb-6 p-4">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            value={callId}
            onChange={(e) => setCallId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && callId && setActiveCallId(callId)}
            placeholder="Enter call ID to watch"
            className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none"
          />
          <Button onClick={() => setActiveCallId(callId)} disabled={!callId}>
            Watch call
          </Button>
        </div>
      </Card>

      {activeCallId ? (
        <LiveCallPanel callId={activeCallId} />
      ) : (
        <EmptyState
          icon={<LiveIcon />}
          title="No call being monitored"
          description="Paste a call ID above and hit Watch to stream live events."
        />
      )}
    </div>
  );
}
