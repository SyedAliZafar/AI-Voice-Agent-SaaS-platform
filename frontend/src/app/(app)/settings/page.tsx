"use client";

import { useState } from "react";

import Link from "next/link";

import { CreditCardIcon, HashIcon, MicIcon, PlugIcon, PlusIcon } from "@/components/icons";
import { Badge, Button, Card, PageHeader, Skeleton } from "@/components/ui";
import { usePlatformAgents } from "@/hooks/usePlatformAgents";
import { workspace } from "@/lib/workspace";

type Integration = { key: string; name: string; desc: string; connected: boolean };

const INITIAL_INTEGRATIONS: Integration[] = [
  { key: "hubspot", name: "HubSpot", desc: "Sync leads and contacts after each call.", connected: true },
  { key: "salesforce", name: "Salesforce", desc: "Push qualified opportunities to your CRM.", connected: false },
  { key: "gcal", name: "Google Calendar", desc: "Let agents book appointments on live calendars.", connected: true },
];

const PHONE_NUMBERS = [
  { number: "+1 (415) 555-0142", agent: "Sales qualifier", region: "US · CA" },
  { number: "+1 (628) 555-0199", agent: "Support triage", region: "US · CA" },
];

export default function SettingsPage() {
  const [integrations, setIntegrations] = useState(INITIAL_INTEGRATIONS);

  // The same live probe the dashboard's RetellStatus uses. This card used to hardcode a
  // green "Connected" badge, which meant a dead Retell account showed red on /dashboard
  // and green here — and this page is where you'd come to check.
  const {
    agents: platformAgents,
    loading: platformLoading,
    error: platformError,
  } = usePlatformAgents();
  const retellOk = !platformError;

  const toggle = (key: string) =>
    setIntegrations((prev) =>
      prev.map((i) => (i.key === key ? { ...i, connected: !i.connected } : i)),
    );

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
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {integrations.map((i) => (
            <Card key={i.key} className="flex flex-col p-4">
              <div className="mb-2 flex items-center justify-between">
                <p className="font-medium text-slate-900">{i.name}</p>
                <Badge tone={i.connected ? "success" : "neutral"}>
                  {i.connected ? "Connected" : "Off"}
                </Badge>
              </div>
              <p className="flex-1 text-sm text-slate-500">{i.desc}</p>
              <Button
                variant={i.connected ? "secondary" : "primary"}
                size="sm"
                className="mt-4 w-full"
                onClick={() => toggle(i.key)}
              >
                {i.connected ? "Disconnect" : "Connect"}
              </Button>
            </Card>
          ))}
        </div>
      </section>

      {/* Phone numbers */}
      <section className="mb-8">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <HashIcon width={18} height={18} className="text-slate-400" />
            <h2 className="text-sm font-semibold text-slate-900">Phone numbers</h2>
          </div>
          <Button variant="secondary" size="sm" icon={<PlusIcon width={14} height={14} />}>
            Add number
          </Button>
        </div>
        <Card className="p-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs font-medium uppercase tracking-wide text-slate-400">
                <th className="px-3 py-2 font-medium">Number</th>
                <th className="px-3 py-2 font-medium">Assigned agent</th>
                <th className="px-3 py-2 font-medium">Region</th>
              </tr>
            </thead>
            <tbody>
              {PHONE_NUMBERS.map((p) => (
                <tr key={p.number} className="border-t border-slate-50">
                  <td className="px-3 py-2.5 font-mono text-[13px] text-slate-700">{p.number}</td>
                  <td className="px-3 py-2.5 text-slate-600">{p.agent}</td>
                  <td className="px-3 py-2.5 text-slate-500">{p.region}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
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
