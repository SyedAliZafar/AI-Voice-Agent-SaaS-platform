"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { AgentsIcon, CheckIcon, SparkleIcon } from "@/components/icons";
import { Badge, Button, Card, EmptyState, Skeleton, TextInput } from "@/components/ui";
import { createAgentFromTemplate, useAgentTemplates } from "@/hooks/useAgentTemplates";
import { AgentTemplate } from "@/lib/types";

/** Short, human blurbs for the gallery cards — not pulled from the backend, which only
 * returns labels (list_templates() is deliberately light so a gallery fetch doesn't
 * compose all 12 full prompts up front). Mirror scripts/agent_templates/{industries,
 * services}.py's own descriptions when adding a new key here; nothing breaks if a key
 * is missing, the card just shows no blurb. */
const INDUSTRY_BLURB: Record<string, string> = {
  hvac_solar: "Qualifies missed emergency calls and install leads for HVAC/solar businesses.",
  roofing: "Leads on the estimate pipeline — the call a roofer loses to a slower follow-up.",
};

const SERVICE_BLURB: Record<string, string> = {
  ai_automation: "The call itself is the pitch — \"you're talking to the AI right now.\"",
  seo: "Findings-based hook — needs a real per-prospect lookup, not a cold list.",
  web_development: "Frames the prospect's site as a lost-bookings problem, not aesthetics.",
};

const STYLE_BLURB: Record<string, string> = {
  long_detail: "Fuller positioning before qualifying — better for undecided prospects.",
  short_quick: "One-sentence hook, then an early interest check before anything else.",
};

/** Groups the flat template list by the picker's three axes without assuming the
 * shape stays 2x3x2 — reading directly off whatever the backend actually returned so
 * pruning or adding an industry never needs a frontend change. */
function useAxisOptions(templates: AgentTemplate[]) {
  return useMemo(() => {
    const industries = new Map<string, string>();
    const services = new Map<string, string>();
    const styles = new Map<string, string>();
    for (const t of templates) {
      industries.set(t.industry, t.industry_label);
      services.set(t.service, t.service_label);
      styles.set(t.style, t.style_label);
    }
    return {
      industries: [...industries.entries()],
      services: [...services.entries()],
      styles: [...styles.entries()],
    };
  }, [templates]);
}

function PickerCard({
  label,
  blurb,
  selected,
  badge,
  onClick,
}: {
  label: string;
  blurb?: string;
  selected: boolean;
  badge?: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "flex flex-col items-start rounded-xl border p-4 text-left transition-colors " +
        (selected
          ? "border-brand-300 bg-brand-50 ring-1 ring-brand-200"
          : "border-slate-200 bg-white hover:bg-slate-50")
      }
    >
      <div className="flex w-full items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-900">{label}</p>
        <div className="flex items-center gap-1.5">
          {badge}
          {selected && (
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-600 text-white">
              <CheckIcon width={12} height={12} />
            </span>
          )}
        </div>
      </div>
      {blurb && <p className="mt-1.5 text-xs leading-relaxed text-slate-500">{blurb}</p>}
    </button>
  );
}

export function TemplateGallery() {
  const router = useRouter();
  const { templates, loading } = useAgentTemplates();
  const { industries, services, styles } = useAxisOptions(templates);

  const [industry, setIndustry] = useState<string | null>(null);
  const [service, setService] = useState<string | null>(null);
  const [style, setStyle] = useState<string | null>(null);
  const [nameOverride, setNameOverride] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(
    () => templates.find((t) => t.industry === industry && t.service === service && t.style === style) || null,
    [templates, industry, service, style],
  );

  async function create() {
    if (!selected) return;
    setCreating(true);
    setError(null);
    try {
      const agent = await createAgentFromTemplate(selected, nameOverride.trim() || undefined);
      router.push(`/agents/${agent.id}`);
    } catch {
      setError("Could not create the agent. Check the backend logs.");
      setCreating(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  if (templates.length === 0) {
    return (
      <EmptyState
        icon={<AgentsIcon />}
        title="No templates available"
        description="scripts/agent_templates has no industries configured — add one there to see it here."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="mb-2 text-sm font-medium text-slate-700">1. Who is this agent calling?</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {industries.map(([key, label]) => {
            const validated = templates.find((t) => t.industry === key)?.validated;
            return (
              <PickerCard
                key={key}
                label={label}
                blurb={INDUSTRY_BLURB[key]}
                selected={industry === key}
                onClick={() => setIndustry(key)}
                badge={
                  validated ? (
                    <Badge tone="success">Call-tested</Badge>
                  ) : (
                    <Badge tone="neutral">Unvalidated</Badge>
                  )
                }
              />
            );
          })}
        </div>
      </div>

      {industry && (
        <div className="animate-fade-in">
          <p className="mb-2 text-sm font-medium text-slate-700">2. What are you selling?</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {services.map(([key, label]) => (
              <PickerCard
                key={key}
                label={label}
                blurb={SERVICE_BLURB[key]}
                selected={service === key}
                onClick={() => setService(key)}
              />
            ))}
          </div>
        </div>
      )}

      {industry && service && (
        <div className="animate-fade-in">
          <p className="mb-2 text-sm font-medium text-slate-700">3. How much airtime before qualifying?</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {styles.map(([key, label]) => (
              <PickerCard
                key={key}
                label={label}
                blurb={STYLE_BLURB[key]}
                selected={style === key}
                onClick={() => setStyle(key)}
              />
            ))}
          </div>
        </div>
      )}

      {selected && (
        <Card className="animate-fade-in flex flex-col gap-4 p-5">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
              <SparkleIcon width={18} height={18} />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-900">{selected.name}</p>
              <p className="mt-0.5 text-xs text-slate-500">
                {selected.validated
                  ? "This vertical's qualifying flow and vocabulary are based on a real call transcript."
                  : "This vertical is written but not yet tuned on a real call — treat the script as a hypothesis until you run one."}
              </p>
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-slate-700">
              Agent name <span className="font-normal text-slate-400">(optional override)</span>
            </label>
            <TextInput
              value={nameOverride}
              onChange={(e) => setNameOverride(e.target.value)}
              placeholder={selected.name}
            />
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <Button onClick={create} disabled={creating} className="self-start">
            {creating ? "Creating…" : "Create agent"}
          </Button>
        </Card>
      )}
    </div>
  );
}
