import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { Lead, LeadStats } from "@/lib/types";

/** Owns the /leads list + /leads/stats fetch, and polls while any lead is "in_flight"
 * so a row's state flips to succeeded/scheduled/exhausted live once the scheduler (or
 * a manual call) resolves it. Fetching lives here per FRONTEND.md — page.tsx and
 * feature components stay presentational.
 */
export function useLeads() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [stats, setStats] = useState<LeadStats | null>(null);
  const [loading, setLoading] = useState(true);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refetch = useCallback(async () => {
    const res = await api.get<Lead[]>("/leads", { params: { limit: 500 } });
    setLeads(res.data);
    api
      .get<LeadStats>("/leads/stats")
      .then((s) => setStats(s.data))
      .catch(() => {});
    return res.data;
  }, []);

  useEffect(() => {
    refetch()
      .catch(() => setLeads([]))
      .finally(() => setLoading(false));
  }, [refetch]);

  useEffect(() => {
    const hasInFlight = leads.some((l) => l.retry_state === "in_flight");
    if (hasInFlight && !pollRef.current) {
      pollRef.current = setInterval(() => {
        refetch().catch(() => {});
      }, 5000);
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
  }, [leads, refetch]);

  return { leads, stats, loading, refetch };
}
