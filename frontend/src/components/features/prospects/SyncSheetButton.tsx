"use client";

import { useState } from "react";

import { Button } from "@/components/ui";
import { api, getApiErrorMessage } from "@/lib/api";

interface SheetSyncResult {
  rows_read: number;
  created: number;
  updated: number;
  queued: number;
  written: number;
}

/** One round trip with the connected Google Sheet: pull the operator's edits in, then
 * push call outcomes back out.
 *
 * Manual on purpose — pressing this button IS the conflict resolution, because only the
 * operator knows whether they just edited the sheet or just ran a batch of calls. See
 * backend/services/sheets_service.py's module docstring for why a live bidirectional
 * sync is the wrong thing to build against an API with no cell-edit webhook.
 */
export function SyncSheetButton({ onSynced }: { onSynced: () => void }) {
  const [syncing, setSyncing] = useState(false);
  const [summary, setSummary] = useState("");

  async function sync() {
    setSyncing(true);
    setSummary("");
    try {
      const res = await api.post<SheetSyncResult>("/prospects/sync-sheet");
      const { created, updated, queued, written } = res.data;
      const parts = [`${written} row${written === 1 ? "" : "s"} in sheet`];
      if (created) parts.push(`${created} new`);
      if (updated) parts.push(`${updated} updated`);
      if (queued) parts.push(`${queued} queued to call again`);
      setSummary(parts.join(" · "));
      onSynced();
    } catch (err) {
      setSummary(getApiErrorMessage(err, "Sheet sync failed."));
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
        title="Pull edits from the Google Sheet, then write call outcomes back to it"
      >
        {syncing ? "Syncing…" : "Sync sheet"}
      </Button>
      {summary && (
        <p className="absolute right-0 top-full mt-1.5 w-64 text-right text-xs text-slate-500">
          {summary}
        </p>
      )}
    </div>
  );
}
