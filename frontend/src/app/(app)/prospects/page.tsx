"use client";

import { Suspense, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { CsvImportButton } from "@/components/features/prospects/CsvImportButton";
import { SyncCallsButton } from "@/components/features/prospects/SyncCallsButton";
import { SyncSheetButton } from "@/components/features/prospects/SyncSheetButton";
import { ProspectCallDrawer } from "@/components/features/prospects/ProspectCallDrawer";
import { ProspectFilters } from "@/components/features/prospects/ProspectFilters";
import { ProspectGroupTree } from "@/components/features/prospects/ProspectGroupTree";
import { ProspectSearchForm } from "@/components/features/prospects/ProspectSearchForm";
import {
  ProspectSection,
  ProspectSectionTabs,
} from "@/components/features/prospects/ProspectSectionTabs";
import { ProspectStatsStrip } from "@/components/features/prospects/ProspectStatsStrip";
import { TargetIcon } from "@/components/icons";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui";
import { useAgents } from "@/hooks/useAgents";
import { useProspects } from "@/hooks/useProspects";
import { groupProspects, sortLabels, UNSPECIFIED } from "@/lib/prospectGrouping";
import { ProspectStatus } from "@/lib/types";

const SECTION_KEYS: ProspectSection[] = [
  "all",
  "not_called",
  "voicemail",
  "called",
  "no_answer",
  "booked",
  "flagged",
  "do_not_call",
];

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
  const sectionParam = searchParams.get("section") || "all";
  const section: ProspectSection = SECTION_KEYS.includes(sectionParam as ProspectSection)
    ? (sectionParam as ProspectSection)
    : "all";

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

  // Which prospect's call drawer is open — looked up against the full `prospects` list
  // (not `filteredProspects`) so it stays resolvable even if a filter change would have
  // dropped its row from view while the drawer is up.
  const [openId, setOpenId] = useState<string | null>(null);
  const openProspect = prospects.find((p) => p.id === openId) || null;

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
    if (section !== "all" && p.status !== (section as ProspectStatus)) return false;
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
        actions={
          <div className="flex items-center gap-2">
            <SyncCallsButton onSynced={() => refetch().catch(() => {})} />
            <SyncSheetButton onSynced={() => refetch().catch(() => {})} />
            <CsvImportButton onImported={() => refetch().catch(() => {})} />
          </div>
        }
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
          <ProspectSectionTabs
            active={section}
            stats={stats}
            onChange={(s) => setParam("section", s === "all" ? "" : s)}
          />
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
          title={section === "all" ? "No prospects match these filters" : "Nothing in this section"}
          description={
            section === "all"
              ? "Try a different country, category, or city, or clear the filters above."
              : "No prospects have this status yet. Pick another section, or run some calls."
          }
        />
      ) : (
        <ProspectGroupTree
          groups={grouped}
          openId={openId}
          onOpenCall={(id) => setOpenId(openId === id ? null : id)}
          onChanged={() => refetch().catch(() => {})}
        />
      )}

      <ProspectCallDrawer
        prospect={openProspect}
        agents={retellAgents}
        onClose={() => setOpenId(null)}
        onChanged={() => refetch().catch(() => {})}
      />
    </div>
  );
}
