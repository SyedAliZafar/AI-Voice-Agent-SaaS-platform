import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { CallEvent } from "@/lib/types";

/**
 * One call's server-side audit trail — every tool dispatch and its result, each turn's
 * LLM timings, an IVR auto-hangup.
 *
 * An empty trail is a normal, expected answer, not a failure: a call answered by the
 * platform's own hosted LLM never touches the code that writes these rows. So the
 * component's job is to say "nothing was recorded for this call" rather than to show an
 * error — which is why `error` here is reserved for the request itself failing.
 *
 * Deliberately not polled. Unlike the calls list (which polls while something is
 * in_progress because a webhook can resolve a call server-side under an open tab), the
 * trail is read after the fact; a live call's trail is written mid-turn and is not what
 * an operator is watching. `reload` covers the rare case of looking at a call that is
 * still running.
 */
export function useCallEvents(callId: string) {
  const [events, setEvents] = useState<CallEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<CallEvent[]>(`/calls/${callId}/events`)
      .then((res) => !cancelled && setEvents(res.data))
      .catch((err) => {
        if (cancelled) return;
        setEvents([]);
        // A 404 means the call itself is gone, which the page already reports from its
        // own fetch — no need to say it twice in the timeline card.
        if (err?.response?.status !== 404) {
          setError("Couldn't load this call's activity.");
        }
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [callId, reloadKey]);

  return { events, loading, error, reload: () => setReloadKey((k) => k + 1) };
}
