"use client";

import { useState } from "react";

import { Button } from "@/components/ui";
import { api, getApiErrorMessage } from "@/lib/api";

interface CallSyncResult {
  fetched: number;
  created: number;
  updated: number;
  matched: number;
  unmatched: number;
}

/** Pulls the voice platform's own call history and reconciles it into the prospect
 * ledger — the answer to "which of these did we actually call, and what happened".
 * Calls placed from Retell's dashboard never created a local record, so without this
 * every one of those prospects reads "not called". Safe to re-run; it's idempotent.
 */
export function SyncCallsButton({ onSynced }: { onSynced: () => void }) {
  const [syncing, setSyncing] = useState(false);
  const [summary, setSummary] = useState("");

  async function sync() {
    setSyncing(true);
    setSummary("");
    try {
      const res = await api.post<CallSyncResult>("/prospects/sync-calls");
      const { fetched, matched, unmatched } = res.data;
      setSummary(
        `Synced ${fetched} call${fetched === 1 ? "" : "s"} · ${matched} matched a prospect` +
          (unmatched ? ` · ${unmatched} unmatched` : ""),
      );
      onSynced();
    } catch (err) {
      setSummary(getApiErrorMessage(err, "Sync failed."));
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="relative">
      <Button
        variant="secondary"
        size="sm"
        onClick={sync}
        disabled={syncing}
        title="Pull call history from the voice platform and update who's been called"
      >
        {syncing ? "Syncing…" : "Sync calls"}
      </Button>
      {summary && (
        <p className="absolute right-0 top-full mt-1.5 w-64 text-right text-xs text-slate-500">
          {summary}
        </p>
      )}
    </div>
  );
}
