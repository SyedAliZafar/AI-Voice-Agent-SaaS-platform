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
    # translated to wss:// when registering that URL with Retell. The quick tunnel's
    # host changes every restart — update this and re-provision when that happens
    # (backend/services/test_call_service.py detects the mismatch and re-provisions
    # automatically the next time a call is placed).
    public_base_url: str = ""
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
