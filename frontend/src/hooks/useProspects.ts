import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { Prospect, ProspectStats } from "@/lib/types";

/** Owns the /prospects list + /prospects/stats fetch, and polls while any row is
 * still pending/running research so rows flip to "KB ready" live. Fetching lives
 * here per FRONTEND.md — page.tsx and feature components stay presentational.
 */
export function useProspects() {
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [stats, setStats] = useState<ProspectStats | null>(null);
  const [loading, setLoading] = useState(true);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
    if (hasInFlight && !pollRef.current) {
      pollRef.current = setInterval(() => {
        refetch().catch(() => {});
      }, 4000);
    }
    if (!hasInFlight && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
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
