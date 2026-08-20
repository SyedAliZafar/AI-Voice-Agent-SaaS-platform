export interface Agent {
  id: string;
  name: string;
  system_prompt: string;
  voice_config: Record<string, unknown>;
  platform: "retell" | "vapi";
  // false -> Retell's built-in LLM answers. true -> our Custom LLM websocket answers
  // with DeepSeek/OpenAI + server-side tools (needs PUBLIC_BASE_URL + a running tunnel).
  use_custom_llm: boolean;
  // Model id, e.g. "deepseek-chat" or "gpt-4o-mini". "" means "use the backend's
  // default_llm_model". Only takes effect when use_custom_llm is true.
  llm_model: string;
  created_at: string;
}

/** An agent that lives on the voice platform itself — built in Retell's own dashboard,
 * never provisioned by this backend. Read-only and fetched live from
 * GET /agents/platform, so there's no local `id`: `external_id` is the platform's own
 * id and the only handle a dial needs. Dialing one of these runs the platform's own
 * LLM, prompt and voice — our conversation engine and server-side tools are not
 * involved. */
export interface PlatformAgent {
  external_id: string;
  name: string;
  voice_id: string | null;
  /** Platform response-engine kind — "retell-llm" means the platform's own brain
   * answers; "custom-llm" means it calls out to a websocket (possibly not ours). */
  engine: string | null;
  version: number | null;
  last_modified_ms: number | null;
}

export interface LlmModel {
  id: string;
  label: string;
  provider: string;
  configured: boolean; // whether that provider's API key is set on the backend
}

export interface LlmModelsResponse {
  models: LlmModel[];
  default: string;
}

export interface AmbientSound {
  id: string;
  label: string;
}

export interface AmbientSoundsResponse {
  options: AmbientSound[];
  // The fleet-wide fallback every agent inherits unless voice_config has its own
  // "ambientSound" key (including explicit `null` for "this campaign is silent").
  default: string | null;
}

export interface CityAutocompleteResult {
  place_id: string;
  label: string;
}

export interface CityAutocompleteResponse {
  suggestions: CityAutocompleteResult[];
}

export interface SandboxMessage {
  role: "user" | "assistant";
  content: string;
}

export interface SandboxChatRequest {
  messages: SandboxMessage[];
  system_prompt_override?: string | null;
  model?: string | null;
  tools_enabled?: boolean;
}

export interface SandboxChatResponse {
  reply: string;
  model: string;
  tools_enabled: boolean;
  // The exact system prompt this turn ran against (agent's saved prompt, or the
  // personalized override for a prospect sandbox) — lets the UI show it verbatim.
  system_prompt: string;
}

export interface Call {
  id: string;
  // Null when the call was placed through a platform-native agent (see PlatformAgent) —
  // those have no local Agent row and carry external_agent_id instead. Exactly one of
  // the two is set on any given call.
  agent_id: string | null;
  external_agent_id: string | null;
  caller_number: string;
  status: "in_progress" | "resolved" | "escalated" | "failed";
  duration_sec: number;
  sentiment_score: number | null;
  started_at: string;
  cost_usd: number;
}

export interface TranscriptTurn {
  role: "caller" | "agent";
  text: string;
  ts: string;
}

export interface Transcript {
  call_id: string;
  full_text: string;
  turns: TranscriptTurn[];
  s3_audio_url: string | null;
}

export interface DailySummary {
  total_calls: number;
  avg_duration_sec: number;
  resolution_rate: number;
  escalated_count: number;
}

export interface CompanyResearch {
  summary: string;
  industry: string;
  size_hint: string;
  pain_points: string[];
  hooks: string[];
  talking_points: string[];
  do_not_mention: string[];
  sources: string[];
}

export type ResearchStatus = "pending" | "running" | "ready" | "failed";
export type OutreachStatus = "not_reached" | "reached" | "callback" | "do_not_call";

// Campaign-outcome axis, set by the operator on /prospects. Overlaps OutreachStatus
// on purpose and is not auto-synced with it — see backend/models/prospect.py.
export type ProspectStatus =
  | "not_called"
  | "called"
  | "booked"
  | "flagged"
  | "no_answer"
  | "do_not_call";

export interface ProspectStats {
  total: number;
  not_called: number;
  called: number;
  booked: number;
  flagged: number;
  no_answer: number;
  do_not_call: number;
}

export interface CsvImportResult {
  imported: number;
  skipped_duplicates: number;
  skipped_invalid: number;
  errors: string[];
  // Of the `imported` rows, how many carry a website. Prospects without one get
  // degraded (name-only) research, so the two always sum to `imported`.
  with_website: number;
  without_website: number;
}

export type LeadRetryState =
  | "paused"
  | "scheduled"
  | "in_flight"
  | "succeeded"
  | "exhausted"
  | "do_not_call";

export type LeadStatus = "new" | "contacted" | "booked" | "not_interested" | "unreachable";

export interface Lead {
  id: string;
  contact_name: string | null;
  business_name: string | null;
  phone: string;
  email: string | null;
  city: string | null;
  country: string | null;
  timezone: string | null;

  source: string;
  bark_request_id: string | null;
  service_requested: string | null;
  budget: string | null;
  request_text: string | null;
  received_at: string | null;
  details: Record<string, unknown>;

  // The operator's own hand-written context — the per-lead "holder".
  notes: string | null;
  agent_id: string | null;

  retry_state: LeadRetryState;
  attempt_count: number;
  next_attempt_at: string | null;
  last_attempt_at: string | null;
  last_outcome: string | null;

  status: LeadStatus;
  created_at: string;
}

export interface LeadStats {
  total: number;
  paused: number;
  scheduled: number;
  in_flight: number;
  succeeded: number;
  exhausted: number;
  do_not_call: number;
}

export interface Prospect {
  id: string;
  google_place_id: string;
  name: string;
  website: string | null;
  phone: string | null;
  address: string | null;
  // Structured fields from Google Places' addressComponents, not parsed out of
  // `address`. Null for rows discovered/imported before this existed.
  city: string | null;
  country: string | null;
  category: string | null;
  rating: number | null;
  review_count: number;
  source_query: string;
  // The "where" of the discovery search that found this row. Null for CSV imports and
  // for rows discovered before this was captured.
  source_location: string | null;

  research_status: ResearchStatus;
  research: CompanyResearch;
  research_error: string | null;
  // Operator-written context, injected into the call prompt alongside `research`.
  prospect_notes: string | null;

  outreach_status: OutreachStatus;
  status: ProspectStatus;
  last_called_at: string | null;
  call_count: number;

  priority_score: number;
  created_at: string;
}
