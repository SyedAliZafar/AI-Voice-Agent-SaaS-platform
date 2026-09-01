import { useCallback, useEffect, useState } from "react";

import { api, getApiErrorMessage } from "@/lib/api";
import { Integration, IntegrationTestResult } from "@/lib/types";

/** What the backend accepts, mirrored from integration_config_service's SUPPORTED and
 * ALLOWED_CONFIG_KEYS. Hand-synced like lib/types.ts is, and for the same reason — the
 * backend rejects an unknown key rather than silently storing it, so a form field that
 * drifts from this list fails loudly at save time rather than pretending to connect.
 *
 * `secret` marks a field the backend masks on read: it comes back as "••••••••cd12" and
 * must never be sent back in that form. `google_sheets` deliberately carries no
 * credential at all — the service-account key lives in backend config, not in this row. */
export interface IntegrationField {
  key: string;
  label: string;
  secret?: boolean;
  placeholder?: string;
  required?: boolean;
}

export interface IntegrationProviderSpec {
  kind: string;
  provider: string;
  name: string;
  description: string;
  fields: IntegrationField[];
}

export const INTEGRATION_PROVIDERS: IntegrationProviderSpec[] = [
  {
    kind: "crm",
    provider: "hubspot",
    name: "HubSpot",
    description: "Push contacts and deals after a call ends.",
    fields: [
      {
        key: "api_key",
        label: "Private app token",
        secret: true,
        placeholder: "pat-na1-…",
        required: true,
      },
      { key: "portal_id", label: "Portal ID", placeholder: "optional" },
      { key: "pipeline_id", label: "Pipeline ID", placeholder: "optional" },
      { key: "stage_id", label: "Stage ID", placeholder: "optional" },
    ],
  },
  {
    kind: "sheet",
    provider: "google_sheets",
    name: "Google Sheets",
    description: "Mirror call outcomes into a spreadsheet.",
    fields: [
      { key: "spreadsheet_id", label: "Spreadsheet ID", required: true },
      { key: "sheet_name", label: "Tab name", placeholder: "Sheet1" },
    ],
  },
];

/**
 * A tenant's connected third parties, from the real /integrations API.
 *
 * Two things this hook exists to get right, both of which the previous hardcoded
 * settings list got wrong by construction:
 *
 * 1. **Saving merges.** The backend's PUT merges `config` into what's stored, so a form
 *    that changes only the pipeline id sends only the pipeline id. `save` therefore
 *    forwards exactly the keys it is given — never a whole form object including a
 *    masked secret, which would store "••••••••cd12" as the real credential.
 * 2. **Connected is not a local boolean.** It's the presence of a row, and whether the
 *    credential actually works is a separate question only `test` can answer — which is
 *    why its result is returned rather than folded into the integration's own state.
 */
export function useIntegrations() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    return api
      .get<Integration[]>("/integrations")
      .then((res) => setIntegrations(res.data))
      .catch((err) => {
        setIntegrations([]);
        setError(getApiErrorMessage(err, "Couldn't load your integrations."));
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  /** Create or update one integration. `config` should carry ONLY the keys being
   * changed — see the merge note above. Throws a message fit to show the operator. */
  const save = useCallback(
    async (kind: string, provider: string, config: Record<string, string>, enabled = true) => {
      try {
        const res = await api.put<Integration>(`/integrations/${kind}`, {
          kind,
          provider,
          config,
          enabled,
        });
        setIntegrations((prev) => {
          const rest = prev.filter((i) => i.kind !== kind);
          return [...rest, res.data].sort((a, b) => a.kind.localeCompare(b.kind));
        });
        return res.data;
      } catch (err) {
        throw new Error(getApiErrorMessage(err, "Couldn't save that integration."));
      }
    },
    [],
  );

  const disconnect = useCallback(async (kind: string) => {
    try {
      await api.delete(`/integrations/${kind}`);
      setIntegrations((prev) => prev.filter((i) => i.kind !== kind));
    } catch (err) {
      throw new Error(getApiErrorMessage(err, "Couldn't disconnect that integration."));
    }
  }, []);

  /** Verify the stored credential against the provider. `ok: false` arrives as a 200 —
   * a wrong key is a successful answer, not a request failure — so only a genuine
   * request error throws here. */
  const test = useCallback(async (kind: string) => {
    try {
      const res = await api.post<IntegrationTestResult>(`/integrations/${kind}/test`);
      return res.data;
    } catch (err) {
      throw new Error(getApiErrorMessage(err, "Couldn't reach the provider to test it."));
    }
  }, []);

  return { integrations, loading, error, reload, save, disconnect, test };
}
