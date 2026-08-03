# Future prompt — OpenAI Realtime API integration

Not scheduled yet. Paste the prompt below into a fresh session when it's time to pick this
up. Context for why it's separate, for whoever reads this file cold:

The provider abstraction added in ADR-008 (`backend/services/llm_service.py`) works
because DeepSeek and GPT-4o-style models all speak the same OpenAI-compatible
chat-completions protocol: one HTTP call, text in, text out, called once per Retell
conversation turn (`backend/api/retell_ws.py`). OpenAI's Realtime API is a different shape
entirely — a stateful, persistent WebSocket/WebRTC session with audio in and audio out, not
a per-turn text completion. It doesn't fit `get_agent_response()`'s signature and can't be
added as another `MODEL_CATALOG` entry.

It also raises an architectural question CONTEXT.md's "what NOT to build" list already
took a position on ("Custom STT/TTS — use the voice platform's built-in. Don't reinvent."):
Retell already does STT/TTS and hands us transcribed text over the Custom LLM WebSocket.
Realtime's actual advantage is skipping that STT/TTS round-trip — which only shows up if
it gets the raw call audio directly, i.e. a genuinely different telephony integration, not
a `retell_ws.py` change. A bridged version (Retell STT → text → Realtime → TTS again)
would add complexity without capturing that advantage.

Before building anything, the open question is whether to keep Retell as the telephony
layer at all for a Realtime-backed agent, or go directly against Twilio and hand Realtime
the call audio ourselves — which is a bigger scope change than anything in ADR-002/ADR-003
anticipated.

---

## Prompt to paste

Investigate what it would take to support OpenAI's Realtime API (audio-native, stateful
session — not the chat-completions models already in `backend/services/llm_service.py`'s
`MODEL_CATALOG`) as a conversation engine option for voice agents in this repo.

Read `CONTEXT.md` (architecture, ADRs, "what NOT to build"), `phase0.md`/`phase3.md`
(the Custom LLM WebSocket migration and its latency findings), and
`backend/api/retell_ws.py` + `backend/services/llm_service.py` (today's per-turn
text-in/text-out design, ADR-008) first — this is genuinely new territory relative to
those, not an extension of the existing provider abstraction, so don't assume the current
`get_agent_response()` shape can just be reused.

Specifically work out:
1. Whether Retell stays the telephony layer (and if so, whether Retell exposes any way to
   hand a call to an audio-native LLM directly instead of its text-based Custom LLM
   WebSocket protocol) — or whether this means going directly against Twilio and losing
   Retell's STT/TTS/telephony handling entirely (ADR-002's adapter pattern, and the "don't
   reinvent STT/TTS" rule in CONTEXT.md, both become live questions here).
2. What "per-agent model choice" even means once one option is a completely different
   protocol/session model than the rest of `MODEL_CATALOG` — does the UI need a distinct
   concept from a `<select>` of model ids, e.g. a separate "engine" dimension alongside
   "model"?
3. Cost and latency tradeoffs against the already-measured DeepSeek streaming numbers in
   phase0.md (0.688s p50 TTFT) — Realtime's pitch is lower latency by skipping a
   round-trip, but that only holds if Retell is out of the loop; confirm rather than assume.
4. Server-side tool execution (ADR-003) — Realtime has its own function-calling and
   turn-taking model; work out whether `backend/tools/` can plug into it without a
   parallel tool-execution path.

Come back with a plan, not code — this is a bigger scope question than a typical feature
addition and deserves a design decision before implementation starts.
