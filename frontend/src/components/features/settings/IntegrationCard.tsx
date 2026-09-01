"use client";

import { useState } from "react";

import { IntegrationProviderSpec } from "@/hooks/useIntegrations";
import { Badge, Button, Field, TextInput } from "@/components/ui";
import { Integration, IntegrationTestResult } from "@/lib/types";

/**
 * One connectable third party, backed by the real /integrations API.
 *
 * This card replaced a hardcoded row with a toggle that only changed React state — the
 * page reported "Connected" for a HubSpot account nobody had ever entered a key for.
 * Three properties of the backend it has to respect, all of which the fake version got
 * to ignore:
 *
 *  - **Secrets come back masked.** A stored api_key reads as "••••••••cd12". That string
 *    must never be submitted, or it replaces the real credential with the mask. So a
 *    secret field starts EMPTY with a "already stored" hint, and an empty secret field
 *    on save means "leave it alone", not "clear it".
 *  - **PUT merges.** Only the keys actually typed into are sent, so changing a pipeline
 *    id can't blank the API key that wasn't touched.
 *  - **Connected ≠ working.** A row existing only means someone saved a credential.
 *    Whether it's valid is a separate question, which is what Test answers — and its
 *    `ok: false` is a successful response, not an error.
 */
export function IntegrationCard({
  spec,
  integration,
  onSave,
  onDisconnect,
  onTest,
}: {
  spec: IntegrationProviderSpec;
  integration: Integration | undefined;
  onSave: (
    kind: string,
    provider: string,
    config: Record<string, string>,
    enabled?: boolean,
  ) => Promise<Integration>;
  onDisconnect: (kind: string) => Promise<void>;
  onTest: (kind: string) => Promise<IntegrationTestResult>;
}) {
  const connected = Boolean(integration);
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<null | "save" | "test" | "disconnect">(null);
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<IntegrationTestResult | null>(null);

  function openForm() {
    // Seed from the stored config, but never from a masked secret — those stay blank so
    // an unchanged field submits nothing rather than submitting the mask.
    const seed: Record<string, string> = {};
    for (const field of spec.fields) {
      if (field.secret) continue;
      const stored = integration?.config?.[field.key];
      if (typeof stored === "string") seed[field.key] = stored;
    }
    setValues(seed);
    setTestResult(null);
    setError(null);
    setOpen(true);
  }

  async function save() {
    setBusy("save");
    setError(null);
    try {
      // Blank fields are omitted entirely: for a secret that means "keep the stored
      // one", and for anything else the backend's merge leaves the existing value be.
      // Clearing a key deliberately requires the API's documented empty-string form,
      // which this form doesn't offer yet — a blank box is far more often "I didn't
      // touch this" than "delete it".
      const config = Object.fromEntries(
        Object.entries(values).filter(([, v]) => v.trim() !== ""),
      );
      await onSave(spec.kind, spec.provider, config);
      setOpen(false);
      setValues({});
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function test() {
    setBusy("test");
    setError(null);
    setTestResult(null);
    try {
      setTestResult(await onTest(spec.kind));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function disconnect() {
    if (!window.confirm(`Disconnect ${spec.name}? The stored credentials are deleted.`)) return;
    setBusy("disconnect");
    setError(null);
    try {
      await onDisconnect(spec.kind);
      setOpen(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="font-medium text-slate-900">{spec.name}</p>
        {!connected ? (
          <Badge tone="neutral">Not connected</Badge>
        ) : integration?.enabled === false ? (
          <Badge tone="warning">Disabled</Badge>
        ) : (
          <Badge tone="success">Connected</Badge>
        )}
      </div>

      <p className="text-sm text-slate-500">{spec.description}</p>

      {/* Verification state, straight from the row — never inferred from "we have a
          credential". A key that worked last week and was revoked yesterday still looks
          connected; last_verify_error is the only thing that says otherwise. */}
      {integration?.last_verify_error && (
        <p className="mt-2 rounded-lg border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs text-red-700">
          Last check failed: {integration.last_verify_error}
        </p>
      )}
      {integration?.last_verified_at && !integration.last_verify_error && (
        <p className="mt-2 text-xs text-slate-400">
          Verified {new Date(integration.last_verified_at).toLocaleString()}
        </p>
      )}
      {connected && !integration?.last_verified_at && (
        <p className="mt-2 text-xs text-slate-400">
          Credentials saved but never verified — run a test.
        </p>
      )}

      {testResult && (
        <p
          className={
            "mt-2 rounded-lg px-2.5 py-1.5 text-xs " +
            (testResult.ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700")
          }
        >
          {testResult.ok ? "Works: " : "Failed: "}
          {testResult.detail}
        </p>
      )}

      {error && (
        <p className="mt-2 rounded-lg border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs text-red-700">
          {error}
        </p>
      )}

      {open ? (
        <div className="mt-4 border-t border-slate-100 pt-4">
          {spec.fields.map((field) => {
            const stored = integration?.secrets_set?.includes(field.key);
            return (
              <Field
                key={field.key}
                label={field.label}
                hint={
                  field.secret
                    ? stored
                      ? "A value is stored. Leave blank to keep it, or type a new one to replace it."
                      : "Sent to the server and never shown again."
                    : undefined
                }
              >
                <TextInput
                  type={field.secret ? "password" : "text"}
                  value={values[field.key] ?? ""}
                  placeholder={
                    field.secret && stored
                      ? "•••••••• (unchanged)"
                      : (field.placeholder ?? "")
                  }
                  onChange={(e) =>
                    setValues((prev) => ({ ...prev, [field.key]: e.target.value }))
                  }
                />
              </Field>
            );
          })}

          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={save} disabled={busy !== null}>
              {busy === "save" ? "Saving…" : "Save"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={busy !== null}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" variant={connected ? "secondary" : "primary"} onClick={openForm}>
            {connected ? "Edit" : "Connect"}
          </Button>
          {connected && (
            <>
              <Button size="sm" variant="secondary" onClick={test} disabled={busy !== null}>
                {busy === "test" ? "Testing…" : "Test"}
              </Button>
              <Button size="sm" variant="ghost" onClick={disconnect} disabled={busy !== null}>
                Disconnect
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
