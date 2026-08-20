// DeepSeek "Strategist" — build-time co-pilot for the Agent Builder.
//
// Runs server-side so the DeepSeek key never reaches the browser. Two modes:
//   - "research": light enrichment pass on the target company (stubbed source for now).
//   - "generate": produce the finished sales system_prompt + pitch/objection playbook.
//
// Everything degrades gracefully: if the key is missing or DeepSeek errors, we fall back to the
// deterministic template in lib/builder.ts so the wizard is never blocked.

import { NextResponse } from "next/server";

import { buildFallbackPrompt, CampaignIntake, ObjectionPair } from "@/lib/builder";

export const runtime = "nodejs";

const DEEPSEEK_URL = "https://api.deepseek.com/chat/completions";
const MODEL = "deepseek-chat";

/**
 * Pluggable enrichment seam. TODO: swap for a real web-search / enrichment API
 * (Clearbit, Apollo, Perplexity, etc.). For now it synthesizes a summary from operator input
 * so the research step is wired end-to-end.
 */
function enrichCompany(target: CampaignIntake["target"]): {
  research: string;
  suggestedPain: string[];
} {
  const bits = [
    target.company && `${target.company}`,
    target.industry && `operates in ${target.industry}`,
    target.size && `(${target.size})`,
  ]
    .filter(Boolean)
    .join(" ");

  const research =
    (bits ? `${bits}. ` : "") +
    (target.hypothesizedPain
      ? `Likely feeling pressure around: ${target.hypothesizedPain}.`
      : "Add a suspected pain point to sharpen the pitch.") +
    // Deliberately describes the limitation in the operator's terms rather than naming
    // the function to go edit — this string is rendered in the builder UI, not a log.
    " Based on what you've entered so far — the more detail you give, the sharper the script.";

  const suggestedPain = [
    target.hypothesizedPain,
    target.industry && `Rising cost pressure in ${target.industry}`,
    "Manual work that doesn't scale with headcount",
    "Slow response times to inbound demand",
  ].filter(Boolean) as string[];

  return { research, suggestedPain };
}

interface GenerateResult {
  system_prompt: string;
  valueProp: string;
  benefits: string[];
  objections: ObjectionPair[];
  source: "deepseek" | "template";
}

function templateResult(intake: CampaignIntake): GenerateResult {
  return {
    system_prompt: buildFallbackPrompt(intake),
    valueProp: intake.pitch.valueProp,
    benefits: intake.pitch.benefits,
    objections: intake.pitch.objections,
    source: "template",
  };
}

async function generateWithDeepSeek(intake: CampaignIntake): Promise<GenerateResult> {
  const apiKey = process.env.DEEPSEEK_API_KEY;
  if (!apiKey) return templateResult(intake);

  const system = [
    "You are an elite B2B outbound sales strategist.",
    "Given a campaign intake, produce a phone-call system prompt for an AI Sales Development Rep.",
    "The prompt MUST follow this exact section structure:",
    "[ROLE] [GUARDRAILS] [PERSONALITY] [PITCH] [TOOLS] [ESCALATION] [CONTEXT].",
    "It is an OUTBOUND cold call: open by earning 30 seconds, keep turns short and conversational.",
    "Reference only these real tools: book_appointment, lookup_customer, create_lead, transfer_call, send_sms.",
    "Always include a recorded-call disclosure and honor do-not-call requests in [GUARDRAILS].",
    "Respond ONLY as strict JSON with keys: system_prompt (string), valueProp (string),",
    "benefits (string[]), objections (array of {objection, response}). No prose outside JSON.",
  ].join(" ");

  const user = [
    "Here is the campaign intake as JSON. Sharpen the value prop, write concrete benefit lines,",
    "and draft crisp rebuttals for each objection. Use the seller's proof points where relevant.",
    "For reference, here is a baseline prompt you may improve upon:",
    "```",
    buildFallbackPrompt(intake),
    "```",
    "Intake:",
    JSON.stringify(intake),
  ].join("\n");

  const res = await fetch(DEEPSEEK_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: MODEL,
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
      response_format: { type: "json_object" },
      temperature: 0.7,
      max_tokens: 2048,
    }),
  });

  if (!res.ok) return templateResult(intake);

  const data = await res.json();
  const content = data?.choices?.[0]?.message?.content;
  if (!content) return templateResult(intake);

  const parsed = JSON.parse(content);
  return {
    system_prompt:
      typeof parsed.system_prompt === "string" && parsed.system_prompt.trim()
        ? parsed.system_prompt
        : buildFallbackPrompt(intake),
    valueProp: parsed.valueProp ?? intake.pitch.valueProp,
    benefits: Array.isArray(parsed.benefits) ? parsed.benefits : intake.pitch.benefits,
    objections: Array.isArray(parsed.objections) ? parsed.objections : intake.pitch.objections,
    source: "deepseek",
  };
}

export async function POST(request: Request) {
  let body: { mode?: string; intake?: CampaignIntake };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const { mode, intake } = body;
  if (!intake) {
    return NextResponse.json({ error: "Missing intake" }, { status: 400 });
  }

  try {
    if (mode === "research") {
      return NextResponse.json(enrichCompany(intake.target));
    }
    if (mode === "generate") {
      return NextResponse.json(await generateWithDeepSeek(intake));
    }
    return NextResponse.json({ error: "Unknown mode" }, { status: 400 });
  } catch {
    // Never fail the wizard — fall back to the deterministic template.
    if (mode === "research") {
      return NextResponse.json(enrichCompany(intake.target));
    }
    return NextResponse.json(templateResult(intake));
  }
}
