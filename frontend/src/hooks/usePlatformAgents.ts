import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { PlatformAgent } from "@/lib/types";

interface PlatformAgentsResponse {
  platform: string;
  agents: PlatformAgent[];
}

interface PlatformCallResult {
  call_id: string;
  from_number: string;
  status: string;
  agent_name: string;
}

/**
 * The voice platform's own agent roster — agents built in Retell's dashboard that this
 * backend never provisioned. Unlike useAgents, this is a live passthrough to the
 * platform on every fetch, so `reload` is exposed: an operator who just created an agent
 * in the Retell tab expects it to appear here without a page refresh.
 *
 * `error` is surfaced rather than swallowed to an empty list (useAgents' approach)
 * because an empty roster and a broken RETELL_API_KEY look identical otherwise, and the
 * fix for each is completely different.
 */
export function usePlatformAgents() {
  const [agents, setAgents] = useState<PlatformAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .get<PlatformAgentsResponse>("/agents/platform")
      .then((res) => setAgents(res.data.agents))
      .catch((err) => {
        setAgents([]);
        setError(err?.response?.data?.detail || "Could not reach the voice platform.");
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(reload, [reload]);

  return { agents, loading, error, reload };
}

/**
 * The `{{placeholder}}` names one platform agent's prompt declares — what the operator
 * must fill before it can be dialed, the same list Retell's dashboard shows.
 *
 * Fetched per agent rather than with the roster: it costs two extra API calls (agent,
 * then its LLM) per agent, which would make listing ten agents thirty requests. The
 * picker only ever needs the one that's selected.
 */
export function usePlatformAgentVariables(externalAgentId: string | null) {
  const [variables, setVariables] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!externalAgentId) {
      setVariables([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .get<{ variables: string[] }>(
        `/agents/platform/${encodeURIComponent(externalAgentId)}/variables`,
      )
      // An unreadable prompt reads as "nothing to fill in" — the backend already
      // returns [] for that case, and the dial itself is the authority on whether
      // something is missing.
      .then((res) => !cancelled && setVariables(res.data.variables))
      .catch(() => !cancelled && setVariables([]))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [externalAgentId]);

  return { variables, loading };
}

/**
 * Dial a number using a platform-native agent. Provisions nothing — the platform's
 * agent brings its own prompt, brain and voice; we contribute the from-number and,
 * via `dynamicVariables`, values for the {{placeholders}} that prompt declares.
 * Returns the placed call, or throws a message suitable for showing the operator.
 */
export async function callPlatformAgent(
  externalAgentId: string,
  toNumber: string,
  dynamicVariables: Record<string, string> = {},
): Promise<PlatformCallResult> {
  try {
    const res = await api.post<PlatformCallResult>("/agents/platform/call", {
      external_agent_id: externalAgentId,
      to_number: toNumber,
      dynamic_variables: dynamicVariables,
    });
    return res.data;
  } catch (err) {
    const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    // FastAPI's 422 for a schema violation is a list of error objects, not a string —
    // rendering that raw shows the operator "[object Object]".
    throw new Error(
      typeof detail === "string" ? detail : "Call failed. Check the number and try again.",
    );
  }
}
