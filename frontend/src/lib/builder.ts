// Sales Agent Builder — the intake model + a deterministic prompt assembler.
//
// The DeepSeek "Strategist" (see app/api/strategist/route.ts) turns a CampaignIntake into a
// finished system_prompt. buildFallbackPrompt() is the offline/degraded path AND the base the
// LLM is asked to improve on, so it lives here as pure TS importable by both server and client.

export type CallObjective = "book_meeting" | "qualify" | "transfer" | "direct_sale";
export type Platform = "retell" | "vapi";

export interface ObjectionPair {
  objection: string;
  response: string;
}

export interface CampaignIntake {
  seller: {
    company: string;
    oneLiner: string;
    website: string;
    offer: string;
    price: string;
    proof: string;
    bookingLink: string;
  };
  goal: {
    objective: CallObjective;
    cta: string;
    successCriteria: string;
  };
  target: {
    company: string;
    industry: string;
    size: string;
    contactName: string;
    contactRole: string;
    hypothesizedPain: string;
    research: string; // filled by the research step (stubbed enrichment)
  };
  pitch: {
    valueProp: string;
    benefits: string[];
    objections: ObjectionPair[];
  };
  persona: {
    agentName: string;
    tone: string;
    pace: string;
    maxWords: number;
    neverSay: string[];
    neverPromise: string[];
    complianceLine: string;
  };
  escalation: {
    transferWhen: string;
    bookVsInfo: string;
  };
  logistics: {
    platform: Platform;
    voiceId: string;
    phoneNumber: string;
    timezone: string;
    callWindow: string;
  };
}

export const OBJECTIVE_LABELS: Record<CallObjective, string> = {
  book_meeting: "Book a meeting / demo",
  qualify: "Qualify the lead",
  transfer: "Warm-transfer to a human",
  direct_sale: "Close a direct sale",
};

export const TONE_OPTIONS = ["Friendly", "Consultative", "Energetic", "Professional", "Warm"];
export const PACE_OPTIONS = ["Relaxed", "Natural", "Brisk"];

// Common cold-call objections, pre-seeded so the operator (or the Strategist) starts from something.
export const STARTER_OBJECTIONS: ObjectionPair[] = [
  { objection: "I'm not interested.", response: "" },
  { objection: "Now's not a good time.", response: "" },
  { objection: "Just send me an email.", response: "" },
  { objection: "We already use someone for this.", response: "" },
  { objection: "How much does it cost?", response: "" },
];

export const DEFAULT_INTAKE: CampaignIntake = {
  seller: { company: "", oneLiner: "", website: "", offer: "", price: "", proof: "", bookingLink: "" },
  goal: { objective: "book_meeting", cta: "", successCriteria: "" },
  target: {
    company: "",
    industry: "",
    size: "",
    contactName: "",
    contactRole: "",
    hypothesizedPain: "",
    research: "",
  },
  pitch: { valueProp: "", benefits: [], objections: STARTER_OBJECTIONS },
  persona: {
    agentName: "",
    tone: "Consultative",
    pace: "Natural",
    maxWords: 60,
    neverSay: [],
    neverPromise: [],
    complianceLine: "This call may be recorded for quality. Let me know anytime if you'd like to opt out.",
  },
  escalation: {
    transferWhen: "The prospect asks to speak to a human, gets frustrated, or is ready to buy.",
    bookVsInfo: "Book the meeting when there's interest; only send info if they explicitly refuse a meeting.",
  },
  logistics: { platform: "retell", voiceId: "", phoneNumber: "", timezone: "", callWindow: "" },
};

export function agentDisplayName(intake: CampaignIntake): string {
  return intake.persona.agentName.trim() || `${intake.seller.company || "New"} SDR`.trim();
}

// The tools the live agent actually has (backend/tools/__init__.py). Referenced in [TOOLS].
const TOOL_LINES = [
  "book_appointment — schedule a meeting/demo on the calendar",
  "lookup_customer — check if the prospect already exists in our records",
  "create_lead — capture a new lead with notes from the call",
  "transfer_call — warm-transfer to a human rep",
  "send_sms — text a follow-up (e.g. a booking link) after the call",
];

/**
 * Deterministic assembler for the [ROLE][GUARDRAILS][PERSONALITY][TOOLS][ESCALATION][CONTEXT]
 * system prompt. Used as the graceful fallback when DeepSeek is unavailable, and as the
 * starting point the Strategist is asked to sharpen.
 */
export function buildFallbackPrompt(intake: CampaignIntake): string {
  const { seller, goal, target, pitch, persona, escalation } = intake;
  const name = agentDisplayName(intake);
  const contact = target.contactName
    ? `${target.contactName}${target.contactRole ? `, ${target.contactRole}` : ""} at ${target.company || "the company"}`
    : target.company || "the prospect";

  const benefits = pitch.benefits.length
    ? pitch.benefits.map((b) => `  - ${b}`).join("\n")
    : "  - (add the top benefits tied to their pain)";

  const objections = pitch.objections.filter((o) => o.objection.trim()).length
    ? pitch.objections
        .filter((o) => o.objection.trim())
        .map((o) => `  - If they say "${o.objection}": ${o.response || "(draft a rebuttal)"}`)
        .join("\n")
    : "  - (add likely objections and how to answer them)";

  return `[ROLE]
You are ${name}, an outbound sales development rep calling on behalf of ${seller.company || "our company"}.
${seller.oneLiner ? `${seller.company} ${seller.oneLiner}.` : ""}
You are calling ${contact}. This is a cold outbound call — open by earning 30 seconds:
briefly say who you are and why you're calling, then ask for permission to continue.
Your single goal this call: ${OBJECTIVE_LABELS[goal.objective]}.${goal.cta ? ` Call to action: ${goal.cta}.` : ""}

[GUARDRAILS]
- ${persona.complianceLine}
- If the prospect asks to be removed or says "do not call", apologize, confirm you'll remove them, and end politely.
${persona.neverSay.length ? persona.neverSay.map((s) => `- Never say: ${s}`).join("\n") : "- Never make claims you can't back up."}
${persona.neverPromise.length ? persona.neverPromise.map((s) => `- Never promise: ${s}`).join("\n") : "- Never promise pricing, timelines, or outcomes you're not authorized to."}

[PERSONALITY]
Tone: ${persona.tone}. Pace: ${persona.pace}. Keep responses under ${persona.maxWords} words — this is a phone call, be conversational, never monologue.

[PITCH]
${pitch.valueProp || "(value proposition)"}
Top benefits:
${benefits}
Objection handling:
${objections}

[TOOLS]
You can call these functions when appropriate:
${TOOL_LINES.map((t) => `  - ${t}`).join("\n")}
When the prospect agrees to the goal, use book_appointment (or create_lead / transfer_call as fits).

[ESCALATION]
Transfer to a human when: ${escalation.transferWhen}
${escalation.bookVsInfo}

[CONTEXT]
Seller: ${seller.company || "n/a"}${seller.website ? ` (${seller.website})` : ""}. Offer: ${seller.offer || "n/a"}. Price: ${seller.price || "n/a"}.
Proof points: ${seller.proof || "n/a"}.
Target: ${target.company || "n/a"}${target.industry ? `, ${target.industry}` : ""}${target.size ? `, ${target.size}` : ""}.
Suspected pain: ${target.hypothesizedPain || "n/a"}.
${target.research ? `Research notes: ${target.research}` : ""}
${seller.bookingLink ? `Booking link (for send_sms follow-up): ${seller.bookingLink}` : ""}`.trim();
}
