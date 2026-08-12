"use client";

import { Button } from "@/components/ui";

interface FilterSelectProps {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  allLabel: string;
}

function FilterSelect({ label, value, options, onChange, allLabel }: FilterSelectProps) {
  return (
    <label className="text-xs font-medium text-slate-500">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="ml-2 rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 focus:border-brand-300 focus:outline-none"
      >
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Industry / service / style filters, parsed from agent names by lib/agentGrouping.ts
 * — mirrors ProspectFilters.tsx's URL-param-backed pattern (shareable, survives
 * refresh) so a growing agent matrix stays browsable instead of one long flat list.
 */
export function AgentFilters({
  industry,
  service,
  style,
  industryOptions,
  serviceOptions,
  styleOptions,
  onIndustryChange,
  onServiceChange,
  onStyleChange,
  onClear,
}: {
  industry: string;
  service: string;
  style: string;
  industryOptions: string[];
  serviceOptions: string[];
  styleOptions: string[];
  onIndustryChange: (value: string) => void;
  onServiceChange: (value: string) => void;
  onStyleChange: (value: string) => void;
  onClear: () => void;
}) {
  const hasFilter = industry || service || style;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <FilterSelect
        label="Industry"
        value={industry}
        options={industryOptions}
        onChange={onIndustryChange}
        allLabel="All industries"
      />
      <FilterSelect
        label="Service"
        value={service}
        options={serviceOptions}
        onChange={onServiceChange}
        allLabel="All services"
      />
      <FilterSelect
        label="Style"
        value={style}
        options={styleOptions}
        onChange={onStyleChange}
        allLabel="All styles"
      />
      {hasFilter && (
        <Button variant="ghost" size="sm" onClick={onClear}>
          Clear filters
        </Button>
      )}
    </div>
  );
}
