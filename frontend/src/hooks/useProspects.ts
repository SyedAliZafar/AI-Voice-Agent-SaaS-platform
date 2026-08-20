import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { Prospect, ProspectStats } from "@/lib/types";

/** Owns the /prospects list + /prospects/stats fetch, and polls while any row is
 * still pending/running research so rows flip to "KB ready" live. Fetching lives
 * here per FRONTEND.md — page.tsx and feature components stay presentational.
 */
// If research is still "pending"/"running" after this long, stop polling for it rather
// than hammering the API forever. Mirrors backend settings.prospect_stale_research_minutes
// — the point at which the *backend* also gives up waiting and treats it as stuck (its
// sweep re-enqueues the task; this just stops a browser tab from polling a row that
// isn't going anywhere on its own). Slight cushion over the backend's threshold so a
// row that's about to be swept isn't given up on here first.
const POLL_TIMEOUT_MS = 25 * 60 * 1000;

export function useProspects() {
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [stats, setStats] = useState<ProspectStats | null>(null);
  const [loading, setLoading] = useState(true);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // When the current run of in-flight rows started polling — reset once nothing is
  // in-flight, so a *new* batch (e.g. a fresh CSV import) gets its own full window
  // rather than inheriting an old batch's near-expired budget.
  const pollStartedAt = useRef<number | null>(null);

  const refetch = useCallback(async () => {
    // The backend defaults to a 100-row page; grouping is client-side over
    // whatever comes back, so a tenant past 100 prospects would silently under-
    // count a country/category/city heading without raising this cap.
    const res = await api.get<Prospect[]>("/prospects", { params: { limit: 500 } });
    setProspects(res.data);
    // Counts come from their own aggregate endpoint rather than the fetched page,
    // which is capped server-side. Fire-and-forget so a stats hiccup can't blank
    // the list.
    api
      .get<ProspectStats>("/prospects/stats")
      .then((s) => setStats(s.data))
      .catch(() => {});
    return res.data;
  }, []);

  useEffect(() => {
    refetch()
      .catch(() => setProspects([]))
      .finally(() => setLoading(false));
  }, [refetch]);

  useEffect(() => {
    const hasInFlight = prospects.some(
      (p) => p.research_status === "pending" || p.research_status === "running",
    );

    if (!hasInFlight) {
      pollStartedAt.current = null;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }

    if (pollStartedAt.current === null) {
      pollStartedAt.current = Date.now();
    }
    // Research genuinely stuck (no worker consuming the queue, or one crashed) used to
    // mean an open /prospects tab refetched the full list every 4s indefinitely — real
    // load on a shared database for a browser tab nobody's watching. This is a client-
    // side backstop for that; the backend's own fix is sweep_stale_prospects below.
    if (Date.now() - pollStartedAt.current > POLL_TIMEOUT_MS) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }

    if (!pollRef.current) {
      pollRef.current = setInterval(() => {
        refetch().catch(() => {});
      }, 4000);
    }

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [prospects, refetch]);

  return { prospects, setProspects, stats, loading, refetch };
}
