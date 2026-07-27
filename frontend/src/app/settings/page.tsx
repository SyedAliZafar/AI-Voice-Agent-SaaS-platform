"use client";

import { useState } from "react";

import { CreditCardIcon, HashIcon, PlugIcon, PlusIcon } from "@/components/icons";
import { Badge, Button, Card, PageHeader } from "@/components/ui";

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

  const toggle = (key: string) =>
    setIntegrations((prev) =>
      prev.map((i) => (i.key === key ? { ...i, connected: !i.connected } : i)),
    );

  return (
    <div className="animate-fade-in">
      <PageHeader title="Settings" subtitle="Manage integrations, phone numbers, and billing." />

      <p className="mb-6 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
        These sections are UI placeholders — wire them to the backend when the endpoints are ready.
      </p>

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
              <p className="font-medium text-slate-900">Free plan</p>
              <Badge tone="brand">Current</Badge>
            </div>
            <p className="mt-1 text-sm text-slate-500">
              1 agent · 100 calls / month. Upgrade for more agents and concurrent calls.
            </p>
          </div>
          <Button>Upgrade plan</Button>
        </Card>
      </section>
    </div>
  );
}
