"use client";

import Link from "next/link";

import { IntegrationCard } from "@/components/features/settings/IntegrationCard";
import { PhoneNumberTable } from "@/components/features/settings/PhoneNumberTable";
import { CreditCardIcon, HashIcon, MicIcon, PlugIcon } from "@/components/icons";
import { Badge, Button, Card, PageHeader, Skeleton } from "@/components/ui";
import { INTEGRATION_PROVIDERS, useIntegrations } from "@/hooks/useIntegrations";
import { usePhoneNumbers } from "@/hooks/usePhoneNumbers";
import { usePlatformAgents } from "@/hooks/usePlatformAgents";
import { workspace } from "@/lib/workspace";

export default function SettingsPage() {
  // The same live probe the dashboard's RetellStatus uses. This card used to hardcode a
  // green "Connected" badge, which meant a dead Retell account showed red on /dashboard
  // and green here — and this page is where you'd come to check.
  const {
    agents: platformAgents,
    loading: platformLoading,
    error: platformError,
  } = usePlatformAgents();
  const retellOk = !platformError;

  // Everything below is now read from its real source for the same reason. The
  // integrations list and phone numbers were the last two hardcoded arrays on this page:
  // both described things outside the browser, and both were describing them wrongly.
  const {
    integrations,
    loading: integrationsLoading,
    error: integrationsError,
    save,
    disconnect,
    test,
  } = useIntegrations();
  const {
    numbers,
    loading: numbersLoading,
    error: numbersError,
  } = usePhoneNumbers();

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Settings"
        subtitle="Manage your voice platform, integrations, phone numbers, and billing."
      />

      {/* Voice platform — the connection everything else depends on, so it leads. */}
      <section className="mb-8">
        <div className="mb-3 flex items-center gap-2">
          <MicIcon width={18} height={18} className="text-slate-400" />
          <h2 className="text-sm font-semibold text-slate-900">Voice platform</h2>
        </div>
        <Card className="flex flex-col items-start justify-between gap-4 p-5 sm:flex-row sm:items-center">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <p className="font-medium text-slate-900">Retell AI</p>
              {platformLoading ? (
                <Skeleton className="h-5 w-20 rounded-full" />
              ) : (
                <Badge tone={retellOk ? "success" : "danger"}>
                  {retellOk ? "Connected" : "Unreachable"}
                </Badge>
              )}
            </div>
            <p className="mt-1 text-sm text-slate-500">
              {platformLoading
                ? "Checking the connection…"
                : retellOk
                  ? `Agents are provisioned and calls placed through this account. ${platformAgents.length} agent${platformAgents.length === 1 ? "" : "s"} on it right now.`
                  : platformError}
            </p>
            <p className="mt-1 text-sm text-slate-500">
              {/* Stated plainly because there is no "connect" flow to send anyone to:
                  the key is one server-side env var, not a per-tenant credential yet
                  (CONTEXT.md ADR-012's known gap). Saying where it lives is more useful
                  than a button that can't do anything. */}
              The API key is read from <code className="text-slate-600">RETELL_API_KEY</code>{" "}
              on the server — it never reaches the browser. Changing it means editing{" "}
              <code className="text-slate-600">.env</code> and restarting the API.
            </p>
          </div>
          {retellOk && !platformLoading && (
            <Link href="/agents?source=platform" className="shrink-0">
              <Button variant="secondary" size="sm">
                View agents
              </Button>
            </Link>
          )}
        </Card>
      </section>

      {/* Integrations */}
      <section className="mb-8">
        <div className="mb-3 flex items-center gap-2">
          <PlugIcon width={18} height={18} className="text-slate-400" />
          <h2 className="text-sm font-semibold text-slate-900">Integrations</h2>
        </div>
        {integrationsError && (
          <p className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {integrationsError}
          </p>
        )}
        {integrationsLoading ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {INTEGRATION_PROVIDERS.map((spec) => (
              <Skeleton key={spec.provider} className="h-40 w-full rounded-2xl" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {/* One card per provider the BACKEND supports, not per row that exists — an
                unconnected provider still needs somewhere to be connected from. The list
                comes from INTEGRATION_PROVIDERS, hand-synced with the backend's
                SUPPORTED/ALLOWED_CONFIG_KEYS. Salesforce and Google Calendar used to
                appear here and are gone: the backend accepts neither, so offering them
                was offering a button that could only ever fail. */}
            {INTEGRATION_PROVIDERS.map((spec) => (
              <IntegrationCard
                key={`${spec.kind}:${spec.provider}`}
                spec={spec}
                integration={integrations.find((i) => i.kind === spec.kind)}
                onSave={save}
                onDisconnect={disconnect}
                onTest={test}
              />
            ))}
          </div>
        )}
        <p className="mt-3 text-xs text-slate-400">
          Calendar booking credentials aren&apos;t here yet — an agent&apos;s Cal.com key
          lives on its tool config and still has to be set in the database directly.
        </p>
      </section>

      {/* Phone numbers */}
      <section className="mb-8">
        <div className="mb-3 flex items-center gap-2">
          <HashIcon width={18} height={18} className="text-slate-400" />
          <h2 className="text-sm font-semibold text-slate-900">Phone numbers</h2>
        </div>
        {/* The "Add number" button that used to sit here had no handler. Numbers are
            bought and imported in the voice platform's own dashboard, so there is no
            in-app flow to send anyone to — same reasoning as the Retell card's missing
            "Manage" button. */}
        <Card className="p-2">
          <PhoneNumberTable
            numbers={numbers}
            agents={platformAgents}
            loading={numbersLoading}
            error={numbersError}
          />
        </Card>
        <p className="mt-3 text-xs text-slate-400">
          Read live from the voice platform account. Numbers are added or released in its
          dashboard, not here.
        </p>
      </section>

      {/* Billing */}
      <section>
        <div className="mb-3 flex items-center gap-2">
          <CreditCardIcon width={18} height={18} className="text-slate-400" />
          <h2 className="text-sm font-semibold text-slate-900">Billing</h2>
        </div>
        <Card className="flex flex-col items-start justify-between gap-4 p-5 sm:flex-row sm:items-center">
          <div>
            <div className="flex items-center gap-2">
              <p className="font-medium text-slate-900">{workspace.plan}</p>
              <Badge tone="brand">Current</Badge>
            </div>
            <p className="mt-1 text-sm text-slate-500">
              10 agents · 2,500 calls / month. Telephony minutes are billed by Retell
              directly.
            </p>
          </div>
          <Button variant="secondary">Change plan</Button>
        </Card>
      </section>
    </div>
  );
}
