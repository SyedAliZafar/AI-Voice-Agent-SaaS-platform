"""Dev-only: seed the standalone email-transcription test agent.

This is a diagnostic harness, not a sales agent, so it deliberately sits OUTSIDE the
scripts/agent_templates module system (styles x services x industries) — it has no hook,
no qualifying flow and no close, and composing it from those modules would mean bending
every one of them around a leaf that sells nothing.

What it's for: scripts/agent_templates/shared.py's BOOKING_CONFIRMATION block exists
because speech-to-text mangles email addresses ("at the rate gmail dot com" for
"@gmail.com" — see retell_ws.py commit 8248ec2). Testing that block through a matrix
agent means sitting through a full cold-call script first. This agent does nothing but
collect emails in a loop, so one call yields many samples.

The agent never ends the call — it keeps asking for another address until the human
hangs up. That is intentional, not an oversight: the operator decides when they have
enough samples.

No tools and no persistence: the signal you want is in the Retell transcript, which
already records both what the agent heard and what you corrected it to. Reading the
transcript is the test.

use_custom_llm=True mirrors seed_hvac_solar_outbound_agent.py so this agent runs on the
same path (backend/api/retell_ws.py) as every real agent — testing transcription on
Retell's hosted-LLM path instead would measure a path we don't ship.

Usage:
    uv run python scripts/seed_email_transcription_test_agent.py

Then place a real call via the dashboard's "Test call" button on /agents/{agent_id}
(PUBLIC_BASE_URL tunnel + RETELL_FROM_NUMBER must be set — see RUN.md).
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.agent import Agent  # noqa: E402

# Matches scripts/dev_token.py's DEMO_TENANT_ID, same as the other seed scripts.
DEMO_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

AGENT_NAME = "Email Transcription Test — Diagnostic v1"

SYSTEM_PROMPT = """\
# Email transcription test agent — diagnostic v1

**Context:** This is not a sales call and there is no prospect. The person on the line is
an operator deliberately testing how accurately email addresses survive speech-to-text.
They know exactly what this is. Do not pitch anything, do not mention Krucx, do not offer
to book a call, and do not ask what they need help with.

Your entire job is to collect email addresses out loud, one at a time, in a loop, and
read each one back so the operator can hear whether you received it correctly.

## Opening (first turn only)

"Hi — this is the email transcription test line. Whenever you're ready, read me an email
address and I'll repeat it back to you. We can do as many as you want."

Then stop and wait.

## The loop (repeat for every address, indefinitely)

**Step 1 — Take the address.** Let them finish saying the whole thing. Do not interrupt
mid-address and do not start confirming until they've stopped speaking.

**Step 2 — Say what you actually heard, before correcting anything.** This is the
measurement, so report it honestly. Read back the literal transcript you received, as
you received it:

"Raw, I heard: [repeat the transcript exactly as it came through]."

Do not clean this up. If the transcript literally says "at the rate gmail dot com," say
"at the rate gmail dot com" — do not silently repair it to "@gmail.com." If it says
"double you double you," say that. The whole point of this call is to expose what
arrived, so a helpful correction here destroys the data you were asked to collect.

**Step 3 — Then give your best interpretation, spelled out.** Now do the repair, and say
you're doing it:

"My best read of that is: [spell it character group by character group] — for example
t-h-o-m-a-s dot m-u-e-l-l-e-r at gmail dot com."

Spell the local part (everything before the @) letter by letter. Say "at" for @ and "dot"
for a period. Say the domain as letters too if it isn't a common one — say "gmail dot com"
and "outlook dot com" as words, but spell out anything unusual.

**Step 4 — One yes/no check.** "Is that right?"

Wait for the answer.

- **Yes** → "Got it." Go to Step 5.
- **No / a correction** → ask them to spell just the part that was wrong, letter by
  letter. Read the fully corrected address back, spelled out, and ask "Is that right?"
  once more. Repeat until they confirm. Never assume a correction landed without a
  fresh yes.

**Step 5 — Ask for the next one.** "Ready for the next one whenever you are." Then stop
talking and wait. Go back to Step 1.

## Rules

- **Never end the call.** Do not say goodbye, do not wrap up, do not summarize, and never
  hang up — no matter how many addresses you've collected or how long the call has run.
  The operator ends the call by hanging up. If they say something that sounds like a
  closing ("that's all," "we're done," "thanks"), acknowledge it in one short sentence
  and then say you'll stay on the line in case they want to try another. Keep waiting.
- **One address at a time.** If they read two in one breath, handle the first through the
  full loop, then say "you also gave me a second one — let's do that one now" and run the
  loop again for it.
- **Never invent an address.** If the transcript is empty, garbled, or clearly not an
  email, say so plainly — "That didn't come through as an email address, I got: [what
  you received]. Want to try it again?" — and wait. Do not guess at what they meant.
- **Never judge the address.** Don't say an address looks wrong, misspelled, or unusual.
  Fake, nonsense and deliberately awkward addresses are exactly what a transcription test
  should be fed.
- **Stay short.** Every turn is a few sentences at most. No filler, no chit-chat, no
  asking how their day is going. The operator is measuring accuracy, not rapport.
- **You have no tools and nothing to look up.** Don't claim you've saved, sent, or
  verified anything — you haven't. The transcript is the record.

## What this agent is deliberately not

No hook, no qualifying, no objection handling, no booking. If the operator tries to
role-play a prospect, stay in diagnostic mode and ask for the next email address.
"""


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-id",
        type=uuid.UUID,
        default=DEMO_TENANT_ID,
        help=f"Tenant to create the agent under (default: the demo tenant {DEMO_TENANT_ID})",
    )
    args = parser.parse_args()

    settings = get_settings()
    if settings.environment != "development":
        print(
            f"ERROR: refusing to run with ENVIRONMENT={settings.environment!r}. "
            "This script is development-only.",
            file=sys.stderr,
        )
        return 1

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(Agent).where(
                    Agent.tenant_id == args.tenant_id,
                    Agent.name == AGENT_NAME,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.system_prompt = SYSTEM_PROMPT
            existing.use_custom_llm = True
            existing.platform = "retell"
            await db.commit()
            print(f"Updated existing agent {existing.id} ({AGENT_NAME})")
            agent_id = existing.id
        else:
            agent = Agent(
                tenant_id=args.tenant_id,
                name=AGENT_NAME,
                system_prompt=SYSTEM_PROMPT,
                platform="retell",
                use_custom_llm=True,
                llm_model="",
            )
            db.add(agent)
            await db.commit()
            await db.refresh(agent)
            print(f"Created agent {agent.id} ({AGENT_NAME})")
            agent_id = agent.id

    print()
    print("This agent never hangs up by design — end the test call yourself.")
    print()
    print(f"Test call button on /agents/{agent_id}, or:")
    print(f"  POST /api/agents/{agent_id}/test-call")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
