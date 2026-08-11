"use client";

import { useCityAutocomplete } from "@/hooks/useCityAutocomplete";
import { CityAutocompleteResult } from "@/lib/types";

/** Debounced city input backed by GET /prospects/city-autocomplete (ADR-002 — the
 * Places key stays server-side). Controlled: the parent owns `value`, this owns
 * only the suggestion dropdown's open/loading state.
 */
export function CityAutocomplete({
  value,
  onChange,
  placeholder = "Berlin, Germany",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  const { suggestions, open, query, select, close, openIfHasSuggestions } = useCityAutocomplete();

  function handleChange(next: string) {
    onChange(next);
    query(next);
  }

  function handleSelect(suggestion: CityAutocompleteResult) {
    onChange(suggestion.label);
    select();
  }

  return (
    <div className="relative">
      <input
        value={value}
        onChange={(e) => handleChange(e.target.value)}
        onFocus={openIfHasSuggestions}
        onBlur={() => setTimeout(close, 150)}
        placeholder={placeholder}
        autoComplete="off"
        className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none"
      />
      {open && suggestions.length > 0 && (
        <ul className="absolute z-10 mt-1 w-full rounded-lg border border-slate-200 bg-white py-1 text-sm shadow-lg">
          {suggestions.map((s) => (
            <li key={s.place_id}>
              <button
                type="button"
                // onMouseDown, not onClick: fires before the input's onBlur closes
                // the dropdown, so the click actually lands on the option.
                onMouseDown={() => handleSelect(s)}
                className="block w-full px-3 py-1.5 text-left text-slate-700 hover:bg-slate-50"
              >
                {s.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
