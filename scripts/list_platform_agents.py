"""List the agents on the connected Retell account (ADR-012).

The read-only companion to scripts/kill_calls.py, and useful for the same reason: it
needs only RETELL_API_KEY — no database, no tunnel, no API server — so it answers "what
does Retell actually think exists" when the dashboard's own picker is empty and you need
to know whether that's an API key problem or a genuinely empty account.

    uv run python scripts/list_platform_agents.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.retell_adapter import RetellAdapter  # noqa: E402


async def main() -> int:
    agents = await RetellAdapter().list_platform_agents()
    if not agents:
        print("No agents on this Retell account.")
        return 0

    print(json.dumps(agents, indent=2))
    print(f"\n{len(agents)} agent(s).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
