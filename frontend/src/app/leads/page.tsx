"use client";

import { useState } from "react";

import { LeadCreateForm } from "@/components/features/leads/LeadCreateForm";
import { LeadRow } from "@/components/features/leads/LeadRow";
import { LeadStatsStrip } from "@/components/features/leads/LeadStatsStrip";
import { PhoneIcon } from "@/components/icons";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui";
import { useAgents } from "@/hooks/useAgents";
import { useLeads } from "@/hooks/useLeads";

export default function LeadsPage() {
  const { leads, stats, loading, refetch } = useLeads();
  const { agents } = useAgents();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const retellAgents = agents.filter((a) => a.platform === "retell");

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Leads"
        subtitle="Warm leads you enter by hand — Bark.com and elsewhere. The scheduler keeps trying each one until someone picks up and talks."
      />

      {stats && <LeadStatsStrip stats={stats} />}

      <LeadCreateForm onCreated={() => refetch().catch(() => {})} />

      <div className="mt-6">
        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full rounded-xl" />
            ))}
          </div>
        ) : leads.length === 0 ? (
          <EmptyState
            icon={<PhoneIcon />}
            title="No leads yet"
            description="Add a lead above to start working it — it stays paused until you press Start calling."
          />
        ) : (
          <div className="space-y-3">
            {leads.map((lead) => (
              <LeadRow
                key={lead.id}
                lead={lead}
                agents={retellAgents}
                expanded={expandedId === lead.id}
                onToggleExpand={() => setExpandedId(expandedId === lead.id ? null : lead.id)}
                onChanged={() => refetch().catch(() => {})}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
