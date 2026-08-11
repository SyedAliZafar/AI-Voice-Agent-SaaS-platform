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

/** Country / category / city filters, all URL-param backed by the parent (same
 * pattern CONTEXT.md calls out as the one to copy: shareable, survives refresh).
 */
export function ProspectFilters({
  country,
  category,
  city,
  countryOptions,
  categoryOptions,
  cityOptions,
  onCountryChange,
  onCategoryChange,
  onCityChange,
  onClear,
}: {
  country: string;
  category: string;
  city: string;
  countryOptions: string[];
  categoryOptions: string[];
  cityOptions: string[];
  onCountryChange: (value: string) => void;
  onCategoryChange: (value: string) => void;
  onCityChange: (value: string) => void;
  onClear: () => void;
}) {
  const hasFilter = country || category || city;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <FilterSelect
        label="Country"
        value={country}
        options={countryOptions}
        onChange={onCountryChange}
        allLabel="All countries"
      />
      <FilterSelect
        label="Category"
        value={category}
        options={categoryOptions}
        onChange={onCategoryChange}
        allLabel="All categories"
      />
      <FilterSelect
        label="City"
        value={city}
        options={cityOptions}
        onChange={onCityChange}
        allLabel="All cities"
      />
      {hasFilter && (
        <Button variant="ghost" size="sm" onClick={onClear}>
          Clear filters
        </Button>
      )}
    </div>
  );
}
