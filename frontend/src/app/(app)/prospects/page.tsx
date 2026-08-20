"use client";

import { Suspense, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { CsvImportButton } from "@/components/features/prospects/CsvImportButton";
import { ProspectFilters } from "@/components/features/prospects/ProspectFilters";
import { ProspectGroupTree } from "@/components/features/prospects/ProspectGroupTree";
import { ProspectSearchForm } from "@/components/features/prospects/ProspectSearchForm";
import { ProspectStatsStrip } from "@/components/features/prospects/ProspectStatsStrip";
import { TargetIcon } from "@/components/icons";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui";
import { useAgents } from "@/hooks/useAgents";
import { useProspects } from "@/hooks/useProspects";
import { groupProspects, sortLabels, UNSPECIFIED } from "@/lib/prospectGrouping";

/** useSearchParams() opts this whole tree out of static rendering unless wrapped in
 * Suspense — Next.js requires this at build time. The page has no server data (it's
 * fully client-fetched already), so the fallback below is never actually visible in
 * practice; it exists to satisfy the framework requirement, not to be seen. */
export default function ProspectsPage() {
  return (
    <Suspense fallback={null}>
      <ProspectsPageInner />
    </Suspense>
  );
}

function ProspectsPageInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const countryFilter = searchParams.get("country") || "";
  const categoryFilter = searchParams.get("category") || "";
  const cityFilter = searchParams.get("city") || "";

  // Reflects filters/search terms into the URL (shareable, survives refresh) rather
  // than into component state — searchParams is already the single source of truth.
  function setParam(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  function clearFilters() {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("country");
    params.delete("category");
    params.delete("city");
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  const { prospects, stats, loading, refetch } = useProspects();
  const { agents } = useAgents();

  // Search terms live in local state, seeded from the URL, and are written back to
  // the URL only when a search actually runs (setParam calls in runSearch below) —
  // syncing on every keystroke would thrash the URL bar for no benefit.
  const [query, setQuery] = useState(searchParams.get("q") || "");
  const [location, setLocation] = useState(searchParams.get("where") || "");

  const [expandedId, setExpandedId] = useState<string | null>(null);

  function persistSearchTerms() {
    setParam("q", query);
    setParam("where", location);
  }

  const retellAgents = agents.filter((a) => a.platform === "retell");

  const countryOptions = useMemo(
    () => sortLabels([...new Set(prospects.map((p) => p.country || UNSPECIFIED))]),
    [prospects],
  );
  const categoryOptions = useMemo(
    () => sortLabels([...new Set(prospects.map((p) => p.category || UNSPECIFIED))]),
    [prospects],
  );
  const cityOptions = useMemo(
    () => sortLabels([...new Set(prospects.map((p) => p.city || UNSPECIFIED))]),
    [prospects],
  );

  const filteredProspects = prospects.filter((p) => {
    if (countryFilter && (p.country || UNSPECIFIED) !== countryFilter) return false;
    if (categoryFilter && (p.category || UNSPECIFIED) !== categoryFilter) return false;
    if (cityFilter && (p.city || UNSPECIFIED) !== cityFilter) return false;
    return true;
  });
  const grouped = groupProspects(filteredProspects);

  // The list fetch caps at 500 rows (see useProspects) — stats.total is the real
  // count, so a tenant past that cap sees an honest "showing N of M" rather than a
  // group heading that silently undercounts.
  const showingAll = stats == null || prospects.length >= stats.total;

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Prospects"
        subtitle="Discovery finds companies, research builds their knowledge base — you just pick who to call."
        actions={<CsvImportButton onImported={() => refetch().catch(() => {})} />}
      />

      {stats && <ProspectStatsStrip stats={stats} />}

      <ProspectSearchForm
        query={query}
        onQueryChange={setQuery}
        location={location}
        onLocationChange={setLocation}
        onDiscovered={() => {
          persistSearchTerms();
          refetch().catch(() => {});
        }}
      />

      {!loading && prospects.length > 0 && (
        <>
          <ProspectFilters
            country={countryFilter}
            category={categoryFilter}
            city={cityFilter}
            countryOptions={countryOptions}
            categoryOptions={categoryOptions}
            cityOptions={cityOptions}
            onCountryChange={(v) => setParam("country", v)}
            onCategoryChange={(v) => setParam("category", v)}
            onCityChange={(v) => setParam("city", v)}
            onClear={clearFilters}
          />
          {!showingAll && (
            <p className="mb-4 -mt-2 text-xs text-slate-400">
              Showing {prospects.length} of {stats!.total} prospects.
            </p>
          )}
        </>
      )}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-xl" />
          ))}
        </div>
      ) : prospects.length === 0 ? (
        <EmptyState
          icon={<TargetIcon />}
          title="No prospects yet"
          description="Run a search above to find companies to call."
        />
      ) : filteredProspects.length === 0 ? (
        <EmptyState
          icon={<TargetIcon />}
          title="No prospects match these filters"
          description="Try a different country, category, or city, or clear the filters above."
        />
      ) : (
        <ProspectGroupTree
          groups={grouped}
          retellAgents={retellAgents}
          expandedId={expandedId}
          onToggleExpand={(id) => setExpandedId(expandedId === id ? null : id)}
          onChanged={() => refetch().catch(() => {})}
        />
      )}
    </div>
  );
}
