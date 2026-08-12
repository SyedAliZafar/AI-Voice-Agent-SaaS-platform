"use client";

import { AgentsIcon, ChevronRightIcon } from "@/components/icons";

interface CategoryCount {
  industry: string;
  count: number;
}

/** Landing view for the Agents page: one tile per industry instead of a full card
 * grid, so a growing agent matrix (scripts/build_agent_matrix.py can produce many)
 * stays browsable at a glance. Picking a tile drills into AgentsPage's filtered grid.
 */
export function AgentCategoryTiles({
  categories,
  onSelect,
}: {
  categories: CategoryCount[];
  onSelect: (industry: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {categories.map((c) => (
        <button
          key={c.industry}
          onClick={() => onSelect(c.industry)}
          className="card group flex items-center gap-4 p-5 text-left transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
        >
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white">
            <AgentsIcon width={20} height={20} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold text-slate-900">{c.industry}</p>
            <p className="text-sm text-slate-500">
              {c.count} agent{c.count === 1 ? "" : "s"}
            </p>
          </div>
          <ChevronRightIcon
            width={18}
            height={18}
            className="shrink-0 text-slate-300 transition-colors group-hover:text-brand-500"
          />
        </button>
      ))}
    </div>
  );
}
