"""Centralized app configuration via Pydantic Settings.

All environment-dependent values live here. Never read os.environ directly
elsewhere in the codebase — import get_settings() instead.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://voiceagent:voiceagent@localhost:5432/voiceagent"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    # Model id used when Agent.llm_model is unset ("") — see llm_service.MODEL_CATALOG
    # for the list of ids this can be and services/llm_service.py's provider_for for how
    # a model id maps to a provider/client.
    default_llm_model: str = "deepseek-chat"
    # Kill switch for the streaming custom-LLM path (backend/api/retell_ws.py). False
    # restores the pre-streaming single-frame blocking behavior via
    # llm_service.get_agent_response — see CONTEXT.md's ADR-009.
    llm_streaming_enabled: bool = True
    # How long Retell holds the agent's opener after the person actually answers
    # (ADR-010), giving them room to say "Hello?" first instead of being talked over.
    # Sent as Retell's own begin_message_delay_ms at agent-provisioning time rather than
    # slept for in retell_ws.py: our websocket opens during call *setup*, so any timer
    # we start there has already expired by the time the phone is picked up. Retell is
    # the only side that knows when the call was answered. Max 5000 per Retell's API.
    greeting_delay_ms: int = 1500
    # Hang up automatically when the "caller" turns out to be a phone menu (IVR) rather
    # than a person — see retell_ws._looks_like_ivr. Outbound prospecting hits switchboards
    # constantly, and on call 274a1b16 the agent delivered its opener into "press one for
    # accounts" and was then disconnected by the menu, paying for the airtime.
    #
    # A flag because this is the one place the agent ends a call on its own judgement: a
    # false positive hangs up on a real person. Detection is deliberately strict (two
    # independent menu markers) and this exists so it can be switched off instantly if a
    # real caller ever trips it, without a deploy.
    ivr_auto_hangup_enabled: bool = True
    # Barge-in guard (see retell_ws._should_let_turn_finish). Retell reports an
    # interruption for any caller audio, including a grunt or a "what?" — cancelling the
    # agent mid-word on those produced a death spiral on call b23851eb: every reply was
    # truncated after two words, the caller said "what?" because he heard a fragment,
    # and that "what?" cancelled the next reply too. Nothing broke the loop.
    #
    # A barge-in inside this window of the agent starting to speak is treated as overlap
    # rather than a decision to interrupt: the turn is allowed to finish its sentence and
    # the new turn runs straight after. 0 disables the window (always cancel).
    barge_in_min_turn_ms: int = 400
    # Independently of the window above, a barge-in whose new caller utterance is nothing
    # but backchannel ("yeah", "mhm", "what?") never cancels a turn — see
    # retell_ws._FILLER_UTTERANCES. False restores the old always-cancel behavior.
    barge_in_ignore_filler: bool = True

    # Voice platforms
    retell_api_key: str = ""
    vapi_api_key: str = ""
    # From-number for outbound test calls — set after importing a Twilio number into Retell
    # (see scripts/setup_retell_number.py). Empty until then.
    retell_from_number: str = ""
    retell_default_voice_id: str = "retell-Maren"
    # How readily Retell stops the agent's TTS when it hears the caller: 0 = very hard to
    # interrupt, 1 = stops instantly. Retell's own default is 1.0, and leaving it there is
    # what kept shredding replies even after retell_ws's barge-in guard stopped OUR side
    # cancelling — there are two independent interruption layers and this is the other one
    # (call fae0d38c, 2026-08-19). 0.3 then proved too deaf in the other direction on
    # call 6906e4de ("you just keep on saying something"): our guard can stop GENERATING
    # but cannot retract audio Retell has already buffered, so Retell has to be willing
    # to cut the speech too. 0.5 is the balance point.
    # Sent at agent-provisioning time and part of the
    # provisioning cache key, so it can't be silently lost on re-provision the way a
    # hand-edit in Retell's dashboard is: the backend creates its own agent and a
    # dashboard edit to any other agent has no effect whatsoever.
    retell_interruption_sensitivity: float = 0.5
    # How eagerly the agent starts speaking after the caller finishes (0 = patient, 1 =
    # eager). begin_message_delay_ms already covers "let them say hello first"; this is
    # the gap after every later turn. Leaning eager on purpose: the opener's whole hook
    # is "you're literally talking to the AI right now," and a laggy reply undercuts
    # that in a way a slightly-quick one doesn't.
    retell_responsiveness: float = 0.7
    # Background ambience on the agent's line (Retell enum, e.g. "coffee-shop",
    # "convention-hall") or None for silence. Deliberately off: two separate calls
    # (b23851eb, fae0d38c) had audio-quality complaints from callers, and ambient noise
    # doesn't just risk annoying them — it competes with Retell's own speech recognition
    # on their INCOMING audio, which is how a real word becomes "(unintelligible audio)"
    # and trips the barge-in guard for no reason. The product's hook is voice clarity;
    # don't spend it on atmosphere.
    retell_ambient_sound: str | None = None
    # Lets the TTS engine inflect delivery ([excited]/[pause]-style cues) instead of
    # reading every line flat. Verified accepted for retell-Maren via a disposable probe
    # agent (create + get-agent + delete, no orphan left behind) — Retell's schema
    # doesn't reject it for a "platform"-provider voice the way it might for one that
    # genuinely doesn't support it, but only a real call confirms it's audible, not just
    # accepted.
    retell_expressive_mode: bool = True
    # Deliberately a short, sales-call-safe subset of Retell's full tag list (which also
    # offers "sigh" and "clear throat" — plausible for a support line, a bad look on an
    # outbound pitch, where they could read as the agent being annoyed with the prospect
    # or physically flustered). "empathetic" earns its place after call 6906e4de, where
    # the prospect said the call "feels like shit" and the agent had nothing but words to
    # soften that with.
    retell_expressive_emotion_tags: list[str] = ["emphasis", "curious", "empathetic", "pause"]
    # Our own public https URL (the dev tunnel's address, e.g. the cloudflared
    # trycloudflare.com host — see docker-compose.yml's "tunnel" profile). Retell's
    # Custom LLM WebSocket needs to dial wss://<this host>/llm-websocket, so this gets
    # translated to wss:// when registering that URL with Retell.
    #
    # Set it to the literal sentinel "auto" to have the quick tunnel's current hostname
    # discovered from cloudflared at use time (backend/services/public_url.py) — the
    # quick tunnel changes host on every restart, and hand-editing this file after each
    # one has cost four billed test calls. A literal URL still wins and is what a named
    # tunnel or a real deployment should use. Either way,
    # backend/services/test_call_service.py detects a changed URL and re-provisions the
    # Retell agent automatically on the next call.
    public_base_url: str = ""
    # Where cloudflared's metrics server is listening — only consulted when
    # public_base_url == "auto". Defaults to localhost because host-run tooling
    # (scripts/check_custom_llm.py) can't resolve compose service names; the api and
    # worker containers get CLOUDFLARED_METRICS_URL=http://tunnel-quick:20241 injected
    # in docker-compose.yml, exactly as DATABASE_URL/REDIS_URL are. The tunnel-quick
    # service publishes 20241 so both routes work.
    cloudflared_metrics_url: str = "http://localhost:20241"
    # Verify X-Retell-Signature on incoming /webhooks/retell requests. On by default —
    # the moment a tunnel is up, an unverified webhook lets anyone with the URL forge
    # call events. Turn off only to hand-post test payloads locally (tests do this via
    # the settings override in conftest). Retell signs with the API key carrying the
    # "webhook" badge in their dashboard; if every event fails verification, check that
    # RETELL_API_KEY is that key.
    retell_verify_webhooks: bool = True

    # Telephony
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    # Elastic SIP Trunk domain for the number being imported into Retell, e.g.
    # "yourtrunk.pstn.twilio.com" (see scripts/setup_retell_number.py). Required for
    # Retell's /import-phone-number call — it rejects an empty termination_uri.
    twilio_termination_uri: str = ""
    # SIP trunk credentials from the Credential List you create inside the Twilio Elastic
    # SIP Trunk — NOT your Twilio account SID/auth token. These authenticate the SIP call
    # between Twilio and Retell, a separate credential type from the Twilio API keys above.
    retell_sip_trunk_username: str = ""
    retell_sip_trunk_password: str = ""

    # Prospecting — Google Places discovery + website research
    google_places_api_key: str = ""
    research_max_page_bytes: int = 400_000  # cap scraped HTML so one huge page can't stall a task
    research_http_timeout_sec: float = 10.0
    # Priority weights — tune these once real call outcomes are in. See
    # prospect_service.compute_priority for the formula.
    priority_weight_rating: float = 2.0
    priority_weight_reviews: float = 1.0
    priority_weight_website: float = 1.5
    priority_weight_phone: float = 1.0

    # Lead retry scheduler (ADR-011) — Bark.com and other hand-entered warm leads.
    # Fallback IANA tz for a lead with no timezone of its own.
    default_lead_timezone: str = "Europe/London"
    lead_business_hours_start: int = 9
    lead_business_hours_end: int = 18
    lead_max_attempts: int = 5
    # A lead stuck "in_flight" longer than this (webhook lost, tunnel down) is treated
    # as stale and reconciled via the platform (ADR-007), not left to retry forever.
    lead_stale_in_flight_minutes: int = 20

    # A prospect stuck "pending"/"running" longer than this (research_prospect.delay()
    # enqueued into a queue with no worker consuming it, or a worker that crashed
    # mid-task) is re-enqueued rather than left to sit forever — see
    # prospect_tasks.sweep_stale_prospects.
    prospect_stale_research_minutes: int = 20

    # Storage
    s3_bucket: str = "voiceagent-recordings"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_endpoint_url: str = "http://localhost:9000"

    # Auth
    clerk_secret_key: str = ""
    jwt_secret: str = "change-me-in-production"

    # App
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Celery (dev-only: run tasks inline instead of dispatching to a worker)
    celery_task_always_eager: bool = False

    # Billing — flat per-minute estimate for what a call costs to run (voice platform +
    # telephony + LLM combined), not itemized. Used by schemas.call.CallResponse.cost_usd.
    call_cost_per_minute: float = 0.20


@lru_cache
def get_settings() -> Settings:
    return Settings()
