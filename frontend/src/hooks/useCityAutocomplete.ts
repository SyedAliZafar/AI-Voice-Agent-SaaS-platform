import { useCallback, useRef, useState } from "react";

import { api } from "@/lib/api";
import { CityAutocompleteResponse, CityAutocompleteResult } from "@/lib/types";

/** Debounced type-ahead over GET /prospects/city-autocomplete (ADR-002 — the Places
 * key never reaches the browser, this just proxies suggestions). Owns the Google
 * Autocomplete session token: one per "typing session," regenerated whenever a
 * suggestion is picked or the field is cleared, per Google's session-billing SKU.
 */
export function useCityAutocomplete() {
  const [suggestions, setSuggestions] = useState<CityAutocompleteResult[]>([]);
  const [open, setOpen] = useState(false);

  const sessionTokenRef = useRef<string>(crypto.randomUUID());
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const query = useCallback((value: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (value.trim().length < 2) {
      setSuggestions([]);
      setOpen(false);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.get<CityAutocompleteResponse>("/prospects/city-autocomplete", {
          params: { input: value, session_token: sessionTokenRef.current },
        });
        setSuggestions(res.data.suggestions);
        setOpen(true);
      } catch {
        // Suggestions are a convenience, not a requirement — a failed lookup just
        // means no dropdown, the operator can still type freely.
        setSuggestions([]);
      }
    }, 300);
  }, []);

  const select = useCallback(() => {
    setOpen(false);
    setSuggestions([]);
    // A suggestion was picked — the next session (e.g. the next search) should
    // bill as a new one, per Google's session-token guidance.
    sessionTokenRef.current = crypto.randomUUID();
  }, []);

  const close = useCallback(() => setOpen(false), []);
  const openIfHasSuggestions = useCallback(
    () => setOpen((prev) => prev || suggestions.length > 0),
    [suggestions.length],
  );

  return { suggestions, open, query, select, close, openIfHasSuggestions };
}
