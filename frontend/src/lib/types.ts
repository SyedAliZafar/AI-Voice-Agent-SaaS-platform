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
}

export interface Call {
  id: string;
  agent_id: string;
  caller_number: string;
  status: "in_progress" | "resolved" | "escalated" | "failed";
  duration_sec: number;
  sentiment_score: number | null;
  started_at: string;
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
}

export interface Prospect {
  id: string;
  google_place_id: string;
  name: string;
  website: string | null;
  phone: string | null;
  address: string | null;
  category: string | null;
  rating: number | null;
  review_count: number;
  source_query: string;

  research_status: ResearchStatus;
  research: CompanyResearch;
  research_error: string | null;

  outreach_status: OutreachStatus;
  status: ProspectStatus;
  last_called_at: string | null;
  call_count: number;

  priority_score: number;
  created_at: string;
}
