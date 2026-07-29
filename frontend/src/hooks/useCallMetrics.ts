import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { DailySummary } from "@/lib/types";

export function useCallMetrics() {
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<DailySummary>("/analytics/summary")
      .then((res) => setSummary(res.data))
      .catch(() => setSummary(null))
      .finally(() => setLoading(false));
  }, []);

  return { summary, loading };
}
