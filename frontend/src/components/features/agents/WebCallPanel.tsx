"use client";

import { useEffect, useRef } from "react";

import { MicIcon, PhoneIcon } from "@/components/icons";
import { Badge, Button, Card } from "@/components/ui";
import { useWebCall, WebCallTarget } from "@/hooks/useWebCall";

const STATUS_LABEL: Record<string, string> = {
  idle: "Ready",
  connecting: "Connecting…",
  live: "Live",
  ended: "Call ended",
  error: "Error",
};

/** Talk to an agent through the browser — the client-demo surface.
 *
 * Deliberately not a variant of the test-call form: that one dials a phone and needs
 * RETELL_FROM_NUMBER, while this spends nothing and needs no telephony setup at all.
 * The point is being able to show a client their own agent on a shared screen without
 * opening Retell's dashboard.
 */
export function WebCallPanel({
  target,
  agentName,
  disabledReason,
}: {
  target: WebCallTarget | null;
  agentName?: string;
  /** Why the call can't start yet (e.g. unfilled prompt placeholders). Shown instead of
   * silently disabling the button — an unexplained dead control reads as a bug. */
  disabledReason?: string;
}) {
  const { status, turns, agentTalking, error, start, stop } = useWebCall(target);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Keep the newest turn visible — during a live demo nobody should have to scroll.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const live = status === "live" || status === "connecting";

  return (
    <Card className="flex flex-col gap-4 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-900">Talk to this agent</p>
          <p className="mt-0.5 text-xs text-slate-500">
            Runs in your browser — no phone number, no call charges.
          </p>
        </div>
        <Badge tone={status === "live" ? "success" : status === "error" ? "danger" : "neutral"}>
          {STATUS_LABEL[status] ?? status}
        </Badge>
      </div>

      <div className="flex items-center gap-3">
        {live ? (
          <Button variant="secondary" onClick={stop} icon={<PhoneIcon width={16} height={16} />}>
            End call
          </Button>
        ) : (
          <Button
            onClick={start}
            icon={<MicIcon width={16} height={16} />}
            disabled={!target || Boolean(disabledReason)}
          >
            {status === "ended" || status === "error" ? "Start again" : "Start call"}
          </Button>
        )}

        {status === "live" && (
          <span className="flex items-center gap-2 text-xs text-slate-500">
            <span
              className={
                "h-2 w-2 rounded-full " +
                (agentTalking ? "animate-pulse bg-brand-500" : "bg-slate-300")
              }
            />
            {agentTalking ? `${agentName || "Agent"} is speaking` : "Listening to you"}
          </span>
        )}
      </div>

      {disabledReason && !error && <p className="text-xs text-amber-700">{disabledReason}</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {turns.length > 0 && (
        <div
          ref={scrollRef}
          className="max-h-72 space-y-2 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50/60 p-3"
        >
          {turns.map((turn, i) => (
            <div
              key={i}
              className={turn.role === "agent" ? "text-left" : "text-right"}
            >
              <span
                className={
                  "inline-block max-w-[85%] rounded-xl px-3 py-1.5 text-sm " +
                  (turn.role === "agent"
                    ? "bg-white text-slate-800 shadow-sm"
                    : "bg-brand-600 text-white")
                }
              >
                {turn.content}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
