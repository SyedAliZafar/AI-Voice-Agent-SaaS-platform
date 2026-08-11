"use client";

import { useState } from "react";

import { CityAutocomplete } from "@/components/features/prospects/CityAutocomplete";
import { SearchIcon } from "@/components/icons";
import { Button, Card, Field } from "@/components/ui";
import { api } from "@/lib/api";

/** The single discovery flow: free-text query + city, submitted to
 * POST /prospects/discover (fire-and-forget — discovery + research run in the
 * background, the caller re-fetches shortly after).
 */
export function ProspectSearchForm({
  query,
  onQueryChange,
  location,
  onLocationChange,
  onDiscovered,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  location: string;
  onLocationChange: (value: string) => void;
  onDiscovered: () => void;
}) {
  const [discovering, setDiscovering] = useState(false);

  async function runDiscovery() {
    setDiscovering(true);
    try {
      await api.post("/prospects/discover", {
        query,
        location: location || null,
        radius_m: 20000,
        limit: 20,
      });
      // Discovery + research run in the background — refresh shortly after to
      // catch new rows.
      setTimeout(onDiscovered, 1500);
    } finally {
      setDiscovering(false);
    }
  }

  return (
    <Card className="mb-6 p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto]">
        <Field label="What are you looking for">
          <input
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="dentists, marketing agencies, gyms…"
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none"
          />
        </Field>
        <Field label="Where">
          <CityAutocomplete value={location} onChange={onLocationChange} />
        </Field>
        <div className="flex items-end pb-4">
          <Button
            icon={<SearchIcon width={16} height={16} />}
            onClick={runDiscovery}
            disabled={discovering || !query}
          >
            {discovering ? "Starting…" : "Find companies"}
          </Button>
        </div>
      </div>
      <p className="text-xs text-slate-400">
        Discovery and research run automatically in the background — this page updates as
        companies are found and their knowledge base is built.
      </p>
    </Card>
  );
}
