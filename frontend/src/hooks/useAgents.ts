import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { Agent } from "@/lib/types";

export function useAgents() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<Agent[]>("/agents")
      .then((res) => setAgents(res.data))
      .catch(() => setAgents([]))
      .finally(() => setLoading(false));
  }, []);

  return { agents, loading };
}
