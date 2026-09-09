"""Flag source files that are missing from CONTEXT.md's "Project structure" tree.

Why this exists: the tree is hand-maintained and drifts. It has already gone stale enough
to omit an entire subsystem (the prospecting pipeline) — see EFFICIENCY.md's "Keeping the
map accurate". This is the cheap backstop: it doesn't generate the tree (the per-file
annotations are the whole value and can't be generated), it just tells you which files
you forgot to add.

    uv run python scripts/check_context_tree.py

Exit code is 1 if anything is unlisted, so it can gate a `docs: sync` commit or CI.
A file counts as listed if its basename appears anywhere in the fenced tree block, or —
for frontend components/hooks/lib, which the tree groups by bare name on shared comment
lines ("AgentCard, AgentBuilder, Stepper, ...") — if its extension-less stem does. Loose
on purpose: the goal is catching a whole file nobody added, not enforcing a format.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONTEXT = REPO / "CONTEXT.md"

# Directories whose files should each earn a mention in the tree.
WATCHED = [
    ("backend/models", "*.py"),
    ("backend/schemas", "*.py"),
    ("backend/api", "*.py"),
    ("backend/services", "*.py"),
    ("backend/tools", "*.py"),
    ("backend/workers", "*.py"),
    ("backend/middleware", "*.py"),
    ("frontend/src/hooks", "*.ts*"),
    ("frontend/src/lib", "*.ts*"),
    ("frontend/src/components/features", "*.tsx"),
    ("frontend/src/components/layout", "*.tsx"),
]

IGNORE = {"__init__.py", "__pycache__"}


def tree_block(text: str) -> str:
    m = re.search(r"## Project structure\s*\n+```(.*?)```", text, re.DOTALL)
    if not m:
        sys.exit("could not find the fenced 'Project structure' block in CONTEXT.md")
    return m.group(1)


def main() -> int:
    block = tree_block(CONTEXT.read_text(encoding="utf-8"))
    missing: list[str] = []

    for rel, pattern in WATCHED:
        base = REPO / rel
        if not base.is_dir():
            continue
        for f in sorted(base.rglob(pattern)):
            if f.name in IGNORE or any(part in IGNORE for part in f.parts):
                continue
            listed = f.name in block
            if not listed and rel.startswith("frontend/"):
                # tree groups these by bare stem on shared comment lines
                listed = re.search(rf"\b{re.escape(f.stem)}\b", block) is not None
            if not listed:
                missing.append(str(f.relative_to(REPO)).replace("\\", "/"))

    if missing:
        print("Files missing from CONTEXT.md's structure tree:\n")
        for m in missing:
            print(f"  {m}")
        print(f"\n{len(missing)} unlisted. Add them to the tree (see EFFICIENCY.md).")
        return 1

    print("CONTEXT.md structure tree mentions every watched source file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
