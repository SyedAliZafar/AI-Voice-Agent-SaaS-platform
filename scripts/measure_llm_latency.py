"""Phase 0 go/no-go: measure DeepSeek time-to-first-token under streaming.

Usage:
    uv run python scripts/measure_llm_latency.py
    uv run python scripts/measure_llm_latency.py --runs 30 --model deepseek-chat

Why this exists: CONTEXT.md targets <1.5s for a full LLM round-trip, and on a live phone
call that budget IS the product — anything slower is audible dead air. Today
backend/services/llm_service.py is entirely non-streaming, so before committing to a
Retell custom-LLM websocket (which streams incrementally) we need to know whether the
model can hit first-token fast enough for the architecture to work at all.

What it reports:
  - TTFT (time to first content token) — the number that decides perceived latency,
    because Retell can begin TTS as soon as the first chunk lands.
  - Total completion time — the old non-streaming behaviour, for comparison.

Reads DEEPSEEK_API_KEY from .env via backend.config. Costs a few cents to run.
"""

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

# See setup_retell_number.py — running a script file directly puts scripts/ on sys.path,
# not the repo root, so the local `backend` package isn't importable without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import AsyncOpenAI  # noqa: E402

from backend.config import get_settings  # noqa: E402

# Representative of a real turn: a short system prompt plus a caller utterance mid-call.
# Deliberately not a one-word prompt — prompt length affects TTFT and we want a realistic
# number, not a flattering one.
SYSTEM_PROMPT = (
    "You are Ava, a voice assistant for Northwind Plumbing. Tone: warm, efficient. "
    "Keep responses under 30 words. Never promise same-day service. If the caller asks "
    "for a human, offer to transfer."
)
CONVERSATION = [
    {"role": "user", "content": "Hi, my kitchen sink has been backing up since last night."},
    {"role": "assistant", "content": "Sorry to hear that. Is water still draining at all?"},
    {"role": "user", "content": "Barely. And there's a smell now. Can someone come out today?"},
]


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile — avoids statistics.quantiles' awkwardness on small n."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))
    return ordered[index]


async def one_run(client: AsyncOpenAI, model: str) -> tuple[float, float, str]:
    start = time.perf_counter()
    ttft: float | None = None
    chunks: list[str] = []

    stream = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, *CONVERSATION],
        max_tokens=128,
        stream=True,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        piece = chunk.choices[0].delta.content
        # First *content* token, not the first frame — role-only deltas arrive first and
        # counting them would understate real latency.
        if piece:
            if ttft is None:
                ttft = time.perf_counter() - start
            chunks.append(piece)

    total = time.perf_counter() - start
    return (ttft if ttft is not None else total), total, "".join(chunks)


def report(label: str, values: list[float], budget: float | None = None) -> None:
    print(f"  {label}")
    print(f"    n      = {len(values)}")
    print(f"    min    = {min(values):.3f}s")
    print(f"    p50    = {statistics.median(values):.3f}s")
    print(f"    p95    = {percentile(values, 95):.3f}s")
    print(f"    max    = {max(values):.3f}s")
    if budget is not None:
        p95 = percentile(values, 95)
        verdict = "PASS" if p95 <= budget else "FAIL"
        print(f"    budget = {budget:.2f}s  ->  {verdict} (on p95)")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=20, help="Number of samples (default: 20)")
    parser.add_argument(
        "--warmup",
        type=int,
        default=2,
        help=(
            "Discarded runs before measuring (default: 2). The first call to a cold client "
            "pays DNS + TLS handshake — real ~2.5s vs ~0.7s steady state — which is a "
            "connection-pooling concern, not a model-speed one. A long-lived call server "
            "holds a warm client, so excluding these reflects production behaviour. Pass "
            "--warmup 0 to see the cold-start cost."
        ),
    )
    parser.add_argument(
        "--model", default="deepseek-chat", help="Model id (default: deepseek-chat)"
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=1.5,
        help="Round-trip budget in seconds to judge against (default: 1.5, per CONTEXT.md)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.deepseek_api_key:
        print("ERROR: DEEPSEEK_API_KEY is not set in .env", file=sys.stderr)
        return 1

    client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url="https://api.deepseek.com")

    print(f"Model: {args.model}   Runs: {args.runs}")
    print(
        "Measuring streaming time-to-first-token "
        "(sequential, to avoid self-inflicted queueing)..."
    )
    print()

    for i in range(args.warmup):
        try:
            ttft, _, _ = await one_run(client, args.model)
            print(f"  warmup {i + 1}: ttft={ttft:.3f}s (discarded)")
        except Exception as exc:  # noqa: BLE001
            print(f"  warmup {i + 1}: FAILED ({type(exc).__name__}: {exc})", file=sys.stderr)
    if args.warmup:
        print()

    ttfts: list[float] = []
    totals: list[float] = []
    sample_text = ""

    for i in range(args.runs):
        try:
            ttft, total, text = await one_run(client, args.model)
        except Exception as exc:  # noqa: BLE001 — a spike script should report, not traceback
            print(f"  run {i + 1}: FAILED ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        ttfts.append(ttft)
        totals.append(total)
        sample_text = sample_text or text
        print(f"  run {i + 1:>2}: ttft={ttft:.3f}s  total={total:.3f}s")

    if not ttfts:
        print("\nAll runs failed — check the API key and network.", file=sys.stderr)
        return 1

    print()
    print("=" * 60)
    report("TIME TO FIRST TOKEN (what the caller perceives)", ttfts, budget=args.budget)
    print()
    report("TOTAL COMPLETION (today's non-streaming behaviour)", totals, budget=args.budget)
    print("=" * 60)
    print()
    print(f"Sample response: {sample_text[:200]}")
    print()
    print(
        "Read this as: if TTFT p95 is comfortably under budget but total is not, streaming\n"
        "is what makes the architecture viable and the WS migration is worth it. If TTFT\n"
        "itself blows the budget, no amount of streaming saves it — reconsider the model\n"
        "for the conversational path before building around it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
