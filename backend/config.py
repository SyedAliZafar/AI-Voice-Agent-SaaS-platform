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

    # Voice platforms
    retell_api_key: str = ""
    vapi_api_key: str = ""
    # From-number for outbound test calls — set after importing a Twilio number into Retell
    # (see scripts/setup_retell_number.py). Empty until then.
    retell_from_number: str = ""
    retell_default_voice_id: str = "11labs-Adrian"
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
