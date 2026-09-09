"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, getApiErrorMessage } from "@/lib/api";
import { BatchRun } from "@/lib/types";

const POLL_MS = 3000;

export interface StartBatchRunParams {
  agent_id?: string;
  external_agent_id?: string;
  /** The exact prospects to call, in dial order. When set, the backend ignores the
   * filter fields below — see backend/schemas/batch_run.py. */
  prospect_ids?: string[];
  /** How many to auto-pick. Meaningless (and omitted) when prospect_ids is given. */
  limit?: number;
  city?: string;
  max_call_count?: number;
  dynamic_variables?: Record<string, string>;
}

/** Owns one batch run's lifecycle: start it, then poll it while status is "running".
 *
 * The poll isn't cosmetic — an item only flips from "dialing" to "done"/"skipped" once
 * that call's real terminal webhook reaches the backend and
 * call_service._fanout_post_call hands it to batch_service (see
 * phases/in-progress/serial-batch-calling.md), so this is the only way to see the run
 * actually advance. Polling stops the moment the run leaves "running" — cancelled,
 * done, or failed all end it — so nothing keeps hitting the API after there's nothing
 * left to learn.
 */
export function useBatchRun() {
  const [run, setRun] = useState<BatchRun | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Belt-and-braces: stop polling if the component unmounts (drawer closed) mid-run.
  useEffect(() => stopPolling, [stopPolling]);

  const pollOnce = useCallback(
    async (runId: string) => {
      try {
        const res = await api.get<BatchRun>(`/prospects/batch-runs/${runId}`);
        setRun(res.data);
        if (res.data.status !== "running") stopPolling();
      } catch {
        // A transient fetch failure shouldn't kill the poll loop — the run itself is
        // unaffected server-side; just try again on the next tick.
      }
    },
    [stopPolling],
  );

  async function start(params: StartBatchRunParams) {
    setStarting(true);
    setError("");
    try {
      const res = await api.post<BatchRun>("/prospects/batch-runs", params);
      setRun(res.data);
      stopPolling();
      if (res.data.status === "running") {
        pollRef.current = setInterval(() => pollOnce(res.data.id), POLL_MS);
      }
    } catch (err) {
      setError(getApiErrorMessage(err, "Could not start the batch run."));
    } finally {
      setStarting(false);
    }
  }

  async function cancel() {
    if (!run) return;
    try {
      const res = await api.post<BatchRun>(`/prospects/batch-runs/${run.id}/cancel`);
      setRun(res.data);
      stopPolling();
    } catch (err) {
      setError(getApiErrorMessage(err, "Could not cancel the run."));
    }
  }

  function reset() {
    stopPolling();
    setRun(null);
    setError("");
  }

  return { run, starting, error, start, cancel, reset };
}
