"""Integration model — per-tenant third-party connection settings (phase5 Session 1).

**Why this is not a ToolConfig row.** `ToolConfig` (models/agent.py) already stores
per-tool credentials, so the obvious move would be another row there. It's the wrong
shape for three reasons:

1. It's keyed on `agent_id` and carries no `tenant_id` at all. A CRM connection belongs
   to the tenant, not to one of their agents — a tenant with six agents wants one HubSpot
   connection, not six copies to keep in sync.
2. ADR-003's `caller_context` flattening dumps *every* ToolConfig row's `config` into one
   shared dict during a call, so a CRM key stored there is readable by every tool. That
   leak is deliberate and useful for calendar credentials (see `check_availability`), but
   there's no reason for a live call to be able to read the CRM key at all.
3. There is no CRUD route for `ToolConfig` — rows are inserted by seed script or by hand.
   That's tolerable for a per-agent booking credential set up once; it isn't for a
   connection the operator is expected to manage themselves.

So this is a separate tenant-scoped table with its own router (`api/integrations.py`).

**One row per (tenant, kind).** `kind` is the slot ("crm"), `provider` is what fills it
("hubspot"). A tenant has one CRM, so the pair is unique — swapping providers overwrites
the row rather than accumulating dead ones. Widen this if a tenant ever needs two of the
same kind; nothing here assumes it can't.

**No e-sign row.** We supply the NDA template and send it from our own Dropbox Sign
account, so that credential is platform-level config, not per-tenant. What *is* per-tenant
for the NDA is the party data used as merge fields, which lives on `Tenant` — see
models/tenant.py.

Known gap, inherited from `ToolConfig` rather than introduced here: `config` holds
credentials in plaintext. Encryption at rest is a follow-up. The API never echoes a
secret back (schemas/integration.py masks it), which is a separate concern and *is*
handled.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class Integration(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("tenant_id", "kind", name="uq_integrations_tenant_kind"),)

    # Which slot this fills. "crm" today; see the module docstring before adding more.
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Which provider fills it — "hubspot". Validated against a registry in
    # services/integration_config_service.py, not at the column level, so adding a
    # provider is a one-line change there rather than a migration.
    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    # Provider-specific settings and credentials, e.g.
    # {"api_key": ..., "pipeline_id": ..., "stage_id": ...}. Deliberately a JSON blob:
    # every provider needs a different set, and column-per-field would mean a migration
    # per provider.
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    # Off switch that doesn't require deleting the credentials. The CRM push (Session 2)
    # must check this, not merely the row's existence.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Set by POST /api/integrations/test. Worth persisting rather than only returning:
    # when the nightly CRM sync starts failing, "last verified 3 weeks ago" is the first
    # thing you want to see, and a rotated key is the most likely cause.
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The provider's own error text from the last failed verification, same principle as
    # integration_service._raise_for_status_with_body — a bare "it didn't work" is
    # useless to whoever has to fix it.
    last_verify_error: Mapped[str | None] = mapped_column(Text, nullable=True)
