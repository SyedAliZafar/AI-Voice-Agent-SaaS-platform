"use client";

import { ProspectRow } from "@/components/features/prospects/ProspectRow";
import { CountryGroup } from "@/lib/prospectGrouping";
import { Agent } from "@/lib/types";

/** Renders the four-level hierarchy country -> category -> city -> companies. All
 * current data is UK-only, but nothing here assumes a single country — the tree
 * shape is entirely driven by groupProspects().
 */
export function ProspectGroupTree({
  groups,
  retellAgents,
  expandedId,
  onToggleExpand,
  onChanged,
}: {
  groups: CountryGroup[];
  retellAgents: Agent[];
  expandedId: string | null;
  onToggleExpand: (id: string) => void;
  onChanged: () => void;
}) {
  return (
    <div className="space-y-8">
      {groups.map((countryGroup) => (
        <div key={countryGroup.country}>
          <div className="mb-3 flex items-baseline gap-2 border-b border-slate-200 pb-1.5">
            <h2 className="text-base font-semibold text-slate-900">{countryGroup.country}</h2>
            <span className="text-xs text-slate-400 tabular-nums">({countryGroup.count})</span>
          </div>

          <div className="space-y-5">
            {countryGroup.categories.map((categoryGroup) => (
              <div key={categoryGroup.category}>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {categoryGroup.category}{" "}
                  <span className="tabular-nums text-slate-400">({categoryGroup.count})</span>
                </h3>

                <div className="space-y-4 pl-3">
                  {categoryGroup.cities.map((cityGroup) => (
                    <div key={cityGroup.city}>
                      <h4 className="mb-1.5 text-xs font-medium text-slate-400">
                        {cityGroup.city}{" "}
                        <span className="tabular-nums">({cityGroup.prospects.length})</span>
                      </h4>

                      <div className="space-y-3">
                        {cityGroup.prospects.map((prospect) => (
                          <ProspectRow
                            key={prospect.id}
                            prospect={prospect}
                            retellAgents={retellAgents}
                            expanded={expandedId === prospect.id}
                            onToggleExpand={() => onToggleExpand(prospect.id)}
                            onChanged={onChanged}
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
