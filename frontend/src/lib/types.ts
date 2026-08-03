export interface Agent {
  id: string;
  name: string;
  system_prompt: string;
  voice_config: Record<string, unknown>;
  platform: "retell" | "vapi";
  // false -> Retell's built-in LLM answers. true -> our Custom LLM websocket answers
  // with DeepSeek + server-side tools (needs PUBLIC_BASE_URL + a running tunnel).
  use_custom_llm: boolean;
  created_at: string;
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
  last_called_at: string | null;
  call_count: number;

  priority_score: number;
  created_at: string;
}
