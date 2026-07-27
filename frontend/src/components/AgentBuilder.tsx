"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Stepper } from "@/components/Stepper";
import { Field, Select, TagInput, TextArea, TextInput } from "@/components/form";
import { SparkleIcon } from "@/components/icons";
import { Badge, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { DEMO_TENANT_ID } from "@/lib/constants";
import {
  agentDisplayName,
  CampaignIntake,
  DEFAULT_INTAKE,
  OBJECTIVE_LABELS,
  ObjectionPair,
  PACE_OPTIONS,
  TONE_OPTIONS,
  type CallObjective,
} from "@/lib/builder";

const STEPS = ["Seller", "Goal", "Target", "Pitch", "Persona", "Logistics", "Review"];

interface GenerateResponse {
  system_prompt: string;
  valueProp: string;
  benefits: string[];
  objections: ObjectionPair[];
  source: "deepseek" | "template";
}

export function AgentBuilder() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [intake, setIntake] = useState<CampaignIntake>(DEFAULT_INTAKE);

  const [researching, setResearching] = useState(false);
  const [suggestedPain, setSuggestedPain] = useState<string[]>([]);
  const [generating, setGenerating] = useState(false);
  const [finalPrompt, setFinalPrompt] = useState("");
  const [promptSource, setPromptSource] = useState<"deepseek" | "template" | null>(null);
  const [saving, setSaving] = useState(false);

  // Immutable nested update: update("seller", { company: "x" })
  function update<K extends keyof CampaignIntake>(section: K, patch: Partial<CampaignIntake[K]>) {
    setIntake((prev) => ({ ...prev, [section]: { ...prev[section], ...patch } }));
  }

  async function runResearch() {
    setResearching(true);
    try {
      const res = await fetch("/api/strategist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "research", intake }),
      });
      const data = await res.json();
      update("target", { research: data.research ?? "" });
      setSuggestedPain(Array.isArray(data.suggestedPain) ? data.suggestedPain : []);
    } finally {
      setResearching(false);
    }
  }

  async function runGenerate(): Promise<GenerateResponse | null> {
    setGenerating(true);
    try {
      const res = await fetch("/api/strategist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "generate", intake }),
      });
      return (await res.json()) as GenerateResponse;
    } finally {
      setGenerating(false);
    }
  }

  async function generatePitch() {
    const data = await runGenerate();
    if (!data) return;
    update("pitch", {
      valueProp: data.valueProp || intake.pitch.valueProp,
      benefits: data.benefits?.length ? data.benefits : intake.pitch.benefits,
      objections: data.objections?.length ? data.objections : intake.pitch.objections,
    });
  }

  async function goToReview() {
    setStep(6);
    const data = await runGenerate();
    if (data) {
      setFinalPrompt(data.system_prompt);
      setPromptSource(data.source);
    }
  }

  async function createAgent() {
    setSaving(true);
    try {
      const res = await api.post(
        "/agents",
        {
          name: agentDisplayName(intake),
          platform: intake.logistics.platform,
          system_prompt: finalPrompt,
          voice_config: { voiceId: intake.logistics.voiceId, campaign: intake },
        },
        { params: { tenant_id: DEMO_TENANT_ID } },
      );
      router.push(`/agents/${res.data.id}`);
    } catch {
      setSaving(false);
    }
  }

  const setObjection = (i: number, patch: Partial<ObjectionPair>) =>
    update("pitch", {
      objections: intake.pitch.objections.map((o, idx) => (idx === i ? { ...o, ...patch } : o)),
    });

  return (
    <div className="animate-fade-in">
      <div className="mb-6 overflow-x-auto">
        <Stepper steps={STEPS} current={step} onStepClick={setStep} />
      </div>

      <Card className="p-6">
        {/* ---------------------------------------------------------- Seller */}
        {step === 0 && (
          <Section title="About your company" subtitle="Who's making the offer.">
            <Field label="Company name">
              <TextInput
                value={intake.seller.company}
                onChange={(e) => update("seller", { company: e.target.value })}
                placeholder="Acme Analytics"
              />
            </Field>
            <Field label="One-liner" hint="What you do, in a sentence.">
              <TextInput
                value={intake.seller.oneLiner}
                onChange={(e) => update("seller", { oneLiner: e.target.value })}
                placeholder="helps ecommerce teams cut churn with predictive analytics"
              />
            </Field>
            <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
              <Field label="Website">
                <TextInput
                  value={intake.seller.website}
                  onChange={(e) => update("seller", { website: e.target.value })}
                  placeholder="acme.com"
                />
              </Field>
              <Field label="Price / packaging">
                <TextInput
                  value={intake.seller.price}
                  onChange={(e) => update("seller", { price: e.target.value })}
                  placeholder="from $499/mo"
                />
              </Field>
            </div>
            <Field label="What you're selling">
              <TextArea
                rows={2}
                value={intake.seller.offer}
                onChange={(e) => update("seller", { offer: e.target.value })}
                placeholder="A churn-prediction platform that plugs into Shopify…"
              />
            </Field>
            <Field label="Proof points" hint="Notable customers, results, case studies.">
              <TextArea
                rows={2}
                value={intake.seller.proof}
                onChange={(e) => update("seller", { proof: e.target.value })}
                placeholder="Used by 200+ DTC brands; cut churn 22% for BrandX"
              />
            </Field>
            <Field label="Booking link" hint="Used for SMS follow-ups.">
              <TextInput
                value={intake.seller.bookingLink}
                onChange={(e) => update("seller", { bookingLink: e.target.value })}
                placeholder="cal.com/acme/demo"
              />
            </Field>
          </Section>
        )}

        {/* ------------------------------------------------------------ Goal */}
        {step === 1 && (
          <Section title="Call goal" subtitle="One call, one job.">
            <Field label="Objective">
              <Select
                value={intake.goal.objective}
                onChange={(e) => update("goal", { objective: e.target.value as CallObjective })}
              >
                {Object.entries(OBJECTIVE_LABELS).map(([val, label]) => (
                  <option key={val} value={val}>
                    {label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Call to action" hint="The single ask you want the prospect to say yes to.">
              <TextInput
                value={intake.goal.cta}
                onChange={(e) => update("goal", { cta: e.target.value })}
                placeholder="Book a 20-minute demo this week"
              />
            </Field>
            <Field label="What does success look like?">
              <TextArea
                rows={2}
                value={intake.goal.successCriteria}
                onChange={(e) => update("goal", { successCriteria: e.target.value })}
                placeholder="A confirmed calendar slot with the decision-maker"
              />
            </Field>
          </Section>
        )}

        {/* ---------------------------------------------------------- Target */}
        {step === 2 && (
          <Section title="The target" subtitle="Who you're calling.">
            <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
              <Field label="Company">
                <TextInput
                  value={intake.target.company}
                  onChange={(e) => update("target", { company: e.target.value })}
                  placeholder="Globex Retail"
                />
              </Field>
              <Field label="Industry">
                <TextInput
                  value={intake.target.industry}
                  onChange={(e) => update("target", { industry: e.target.value })}
                  placeholder="Ecommerce / retail"
                />
              </Field>
              <Field label="Company size">
                <TextInput
                  value={intake.target.size}
                  onChange={(e) => update("target", { size: e.target.value })}
                  placeholder="200–500 employees"
                />
              </Field>
              <Field label="Contact name">
                <TextInput
                  value={intake.target.contactName}
                  onChange={(e) => update("target", { contactName: e.target.value })}
                  placeholder="Jordan Lee"
                />
              </Field>
            </div>
            <Field label="Contact role">
              <TextInput
                value={intake.target.contactRole}
                onChange={(e) => update("target", { contactRole: e.target.value })}
                placeholder="VP of Growth"
              />
            </Field>
            <Field label="Suspected pain point">
              <TextInput
                value={intake.target.hypothesizedPain}
                onChange={(e) => update("target", { hypothesizedPain: e.target.value })}
                placeholder="High repeat-purchase drop-off after month 1"
              />
            </Field>

            <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-medium text-slate-700">Research notes</span>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<SparkleIcon width={14} height={14} />}
                  onClick={runResearch}
                  disabled={researching}
                >
                  {researching ? "Researching…" : "Research target"}
                </Button>
              </div>
              <TextArea
                rows={3}
                value={intake.target.research}
                onChange={(e) => update("target", { research: e.target.value })}
                placeholder="Click “Research target” to draft notes, or type your own."
              />
              {suggestedPain.length > 0 && (
                <div className="mt-3">
                  <p className="mb-1.5 text-xs text-slate-500">Suggested pain points — click to use:</p>
                  <div className="flex flex-wrap gap-1.5">
                    {suggestedPain.map((p) => (
                      <button
                        key={p}
                        type="button"
                        onClick={() => update("target", { hypothesizedPain: p })}
                        className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-600 hover:border-brand-300 hover:text-brand-700"
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Section>
        )}

        {/* ----------------------------------------------------------- Pitch */}
        {step === 3 && (
          <Section
            title="The pitch"
            subtitle="Let the Strategist draft it, then edit."
            action={
              <Button
                variant="secondary"
                size="sm"
                icon={<SparkleIcon width={14} height={14} />}
                onClick={generatePitch}
                disabled={generating}
              >
                {generating ? "Generating…" : "Generate with AI"}
              </Button>
            }
          >
            <Field label="Value proposition">
              <TextArea
                rows={2}
                value={intake.pitch.valueProp}
                onChange={(e) => update("pitch", { valueProp: e.target.value })}
                placeholder="We help teams like yours recover lost revenue from churn…"
              />
            </Field>
            <Field label="Top benefits" hint="Tie each to the prospect's pain.">
              <TagInput
                value={intake.pitch.benefits}
                onChange={(benefits) => update("pitch", { benefits })}
                placeholder="Add a benefit and press Enter"
              />
            </Field>
            <div className="mt-2">
              <p className="mb-2 text-sm font-medium text-slate-700">Objection handling</p>
              <div className="space-y-3">
                {intake.pitch.objections.map((o, i) => (
                  <div key={i} className="rounded-xl border border-slate-200 p-3">
                    <TextInput
                      value={o.objection}
                      onChange={(e) => setObjection(i, { objection: e.target.value })}
                      placeholder="Objection"
                      className="mb-2 font-medium"
                    />
                    <TextArea
                      rows={2}
                      value={o.response}
                      onChange={(e) => setObjection(i, { response: e.target.value })}
                      placeholder="How the agent should respond"
                    />
                  </div>
                ))}
              </div>
            </div>
          </Section>
        )}

        {/* --------------------------------------------------------- Persona */}
        {step === 4 && (
          <Section title="Persona & guardrails" subtitle="How the agent sounds and what it must never do.">
            <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
              <Field label="Agent name">
                <TextInput
                  value={intake.persona.agentName}
                  onChange={(e) => update("persona", { agentName: e.target.value })}
                  placeholder="Alex"
                />
              </Field>
              <Field label="Max words per turn">
                <TextInput
                  type="number"
                  value={intake.persona.maxWords}
                  onChange={(e) => update("persona", { maxWords: Number(e.target.value) || 0 })}
                />
              </Field>
              <Field label="Tone">
                <Select
                  value={intake.persona.tone}
                  onChange={(e) => update("persona", { tone: e.target.value })}
                >
                  {TONE_OPTIONS.map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Pace">
                <Select
                  value={intake.persona.pace}
                  onChange={(e) => update("persona", { pace: e.target.value })}
                >
                  {PACE_OPTIONS.map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </Select>
              </Field>
            </div>
            <Field label="Never say">
              <TagInput
                value={intake.persona.neverSay}
                onChange={(neverSay) => update("persona", { neverSay })}
                placeholder="e.g. guaranteed"
              />
            </Field>
            <Field label="Never promise">
              <TagInput
                value={intake.persona.neverPromise}
                onChange={(neverPromise) => update("persona", { neverPromise })}
                placeholder="e.g. specific ROI numbers"
              />
            </Field>
            <Field label="Compliance line" hint="Recorded-call disclosure / opt-out.">
              <TextArea
                rows={2}
                value={intake.persona.complianceLine}
                onChange={(e) => update("persona", { complianceLine: e.target.value })}
              />
            </Field>
          </Section>
        )}

        {/* ------------------------------------------------------- Logistics */}
        {step === 5 && (
          <Section title="Escalation & logistics" subtitle="When to hand off, and where it runs.">
            <Field label="Transfer to a human when…">
              <TextArea
                rows={2}
                value={intake.escalation.transferWhen}
                onChange={(e) => update("escalation", { transferWhen: e.target.value })}
              />
            </Field>
            <Field label="Book vs. send info">
              <TextArea
                rows={2}
                value={intake.escalation.bookVsInfo}
                onChange={(e) => update("escalation", { bookVsInfo: e.target.value })}
              />
            </Field>
            <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
              <Field label="Voice platform">
                <Select
                  value={intake.logistics.platform}
                  onChange={(e) =>
                    update("logistics", { platform: e.target.value as "retell" | "vapi" })
                  }
                >
                  <option value="retell">Retell AI</option>
                  <option value="vapi">Vapi AI</option>
                </Select>
              </Field>
              <Field label="Voice ID" hint="Optional — from your platform.">
                <TextInput
                  value={intake.logistics.voiceId}
                  onChange={(e) => update("logistics", { voiceId: e.target.value })}
                  placeholder="11labs-Adrian"
                />
              </Field>
              <Field label="Timezone">
                <TextInput
                  value={intake.logistics.timezone}
                  onChange={(e) => update("logistics", { timezone: e.target.value })}
                  placeholder="America/Los_Angeles"
                />
              </Field>
              <Field label="Calling window">
                <TextInput
                  value={intake.logistics.callWindow}
                  onChange={(e) => update("logistics", { callWindow: e.target.value })}
                  placeholder="9am–5pm weekdays"
                />
              </Field>
            </div>
          </Section>
        )}

        {/* ---------------------------------------------------------- Review */}
        {step === 6 && (
          <Section
            title="Review & create"
            subtitle="This is the system prompt your live agent will use."
            action={
              promptSource ? (
                <Badge tone={promptSource === "deepseek" ? "brand" : "neutral"}>
                  {promptSource === "deepseek" ? "Generated by DeepSeek" : "Template fallback"}
                </Badge>
              ) : undefined
            }
          >
            {generating && !finalPrompt ? (
              <div className="flex items-center gap-2 py-10 text-sm text-slate-500">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-brand-500" />
                Strategist is writing the prompt…
              </div>
            ) : (
              <>
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-700">
                    {agentDisplayName(intake)} · {intake.logistics.platform}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<SparkleIcon width={14} height={14} />}
                    onClick={goToReview}
                    disabled={generating}
                  >
                    Regenerate
                  </Button>
                </div>
                <TextArea
                  rows={18}
                  value={finalPrompt}
                  onChange={(e) => setFinalPrompt(e.target.value)}
                  className="font-mono text-[13px] leading-relaxed"
                />
              </>
            )}
          </Section>
        )}

        {/* ---------------------------------------------------------- Footer */}
        <div className="mt-6 flex items-center justify-between border-t border-slate-100 pt-5">
          <Button
            variant="ghost"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
          >
            Back
          </Button>
          {step < 5 && <Button onClick={() => setStep((s) => s + 1)}>Continue</Button>}
          {step === 5 && (
            <Button onClick={goToReview} icon={<SparkleIcon width={16} height={16} />}>
              Generate prompt
            </Button>
          )}
          {step === 6 && (
            <Button onClick={createAgent} disabled={saving || !finalPrompt}>
              {saving ? "Creating…" : "Create agent"}
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
}

function Section({
  title,
  subtitle,
  action,
  children,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}
