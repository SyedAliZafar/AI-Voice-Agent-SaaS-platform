"use client";

import { useState } from "react";

import { RefreshIcon } from "@/components/icons";
import { Button } from "@/components/ui";

/**
 * Calls sitting at "in progress" longer than they should — usually a webhook that never
 * arrived (ADR-007). The reconcile button asks the voice platform for the real outcome.
 *
 * This used to be a full-width amber banner naming `PUBLIC_BASE_URL` and "dead tunnel".
 * That's an operator diagnostic, not a user-facing message: it makes the product look
 * broken on the one screen people look at most. The detail is still here — one click
 * away, for whoever actually needs it — but the default state is a quiet, factual row.
 */
export function SyncNotice({
  count,
  syncing,
  note,
  onSync,
}: {
  count: number;
  syncing: boolean;
  note: string | null;
  onSync: () => void;
}) {
  const [showDetail, setShowDetail] = useState(false);

  if (count === 0) return null;

  return (
    <div className="mb-6 rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-slate-600">
          <span className="mr-2 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500 align-middle" />
          {count} call{count === 1 ? "" : "s"} still marked in progress.{" "}
          <button
            onClick={() => setShowDetail((v) => !v)}
            className="font-medium text-slate-500 underline decoration-slate-300 underline-offset-2 hover:text-slate-800"
          >
            {showDetail ? "Hide details" : "Why?"}
          </button>
        </p>

        <div className="flex items-center gap-2">
          {note && <span className="text-xs text-slate-500">{note}</span>}
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshIcon width={14} height={14} />}
            onClick={onSync}
            disabled={syncing}
          >
            {syncing ? "Checking…" : "Refresh status"}
          </Button>
        </div>
      </div>

      {showDetail && (
        <p className="mt-3 border-t border-slate-100 pt-3 text-xs leading-relaxed text-slate-500">
          The voice platform notifies us when a call ends. If that notification is missed —
          a restarted tunnel in development, or an unset{" "}
          <code className="rounded bg-slate-100 px-1 py-0.5 font-mono">PUBLIC_BASE_URL</code> —
          the call stays open on our side even though it finished. Refreshing asks the
          platform directly and writes the real outcome.
        </p>
      )}
    </div>
  );
}
