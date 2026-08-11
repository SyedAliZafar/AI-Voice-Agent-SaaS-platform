"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { RefreshIcon, SearchIcon, TargetIcon } from "@/components/icons";
import { Badge, Button, Card, EmptyState, Field, PageHeader, Skeleton, TextInput } from "@/components/ui";
import { api, getApiErrorMessage } from "@/lib/api";
import {
  Agent,
  CityAutocompleteResponse,
  CityAutocompleteResult,
  CsvImportResult,
  OutreachStatus,
  Prospect,
  ProspectStats,
  ProspectStatus,
  ResearchStatus,
} from "@/lib/types";

const RESEARCH_META: Record<ResearchStatus, { label: string; tone: "neutral" | "info" | "success" | "danger" }> = {
  pending: { label: "Queued", tone: "neutral" },
  running: { label: "Researching…", tone: "info" },
  ready: { label: "KB ready", tone: "success" },
  failed: { label: "Research failed", tone: "danger" },
};

const OUTREACH_META: Record<OutreachStatus, { label: string; tone: "neutral" | "info" | "warning" | "danger" }> = {
  not_reached: { label: "Not reached", tone: "neutral" },
  reached: { label: "Reached", tone: "info" },
  callback: { label: "Callback", tone: "warning" },
  do_not_call: { label: "Do not call", tone: "danger" },
};

// The campaign-outcome axis the operator sets by hand. Separate from OUTREACH_META
// above and not synced with it — see backend/models/prospect.py.
const STATUS_LABELS: Record<ProspectStatus, string> = {
  not_called: "Not called",
  called: "Called",
  booked: "Booked",
  flagged: "Flagged",
  no_answer: "No answer",
  do_not_call: "Do not call",
};

const STATUS_ORDER: ProspectStatus[] = [
  "not_called",
  "called",
  "booked",
  "flagged",
  "no_answer",
  "do_not_call",
];

// Counts shown in the strip, in order. "total" plus the four outcomes worth watching —
// not_called and do_not_call are deliberately left off (they're the residue, and the
// per-row dropdown already shows them).
const STAT_TILES: { key: keyof ProspectStats; label: string }[] = [
  { key: "total", label: "Total" },
  { key: "called", label: "Called" },
  { key: "booked", label: "Booked" },
  { key: "flagged", label: "Flagged" },
  { key: "no_answer", label: "No answer" },
];

const UNSPECIFIED = "Unspecified";

/** Sorts labels alphabetically with the "Unspecified" bucket always last, so it
 * doesn't crowd out real values in either a group heading list or a filter dropdown.
 */
function sortLabels(labels: string[]): string[] {
  return [...labels].sort((a, b) => {
    if (a === UNSPECIFIED) return 1;
    if (b === UNSPECIFIED) return -1;
    return a.localeCompare(b);
  });
}

interface CategoryGroup {
  category: string;
  prospects: Prospect[];
}

interface CountryGroup {
  country: string;
  categories: CategoryGroup[];
  count: number;
}

/** Country -> category -> flat list. City is real data (shown per-row) but is
 * deliberately not a grouping level — two levels is what was asked for. Rows missing
 * either field group under "Unspecified" rather than being dropped. Purely
 * presentational — no backend change, works over whatever /prospects already returned. */
function groupProspects(prospects: Prospect[]): CountryGroup[] {
  const byCountry = new Map<string, Map<string, Prospect[]>>();

  for (const prospect of prospects) {
    const country = prospect.country || UNSPECIFIED;
    const category = prospect.category || UNSPECIFIED;
    if (!byCountry.has(country)) byCountry.set(country, new Map());
    const byCategory = byCountry.get(country)!;
    if (!byCategory.has(category)) byCategory.set(category, []);
    byCategory.get(category)!.push(prospect);
  }

  return sortLabels([...byCountry.keys()]).map((country) => {
    const byCategory = byCountry.get(country)!;
    const categories = sortLabels([...byCategory.keys()]).map((category) => ({
      category,
      prospects: byCategory.get(category)!,
    }));
    return {
      country,
      categories,
      count: categories.reduce((sum, c) => sum + c.prospects.length, 0),
    };
  });
}

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

  // Reflects the filter into the URL (shareable, survives refresh) rather than into
  // component state — searchParams is already the single source of truth for these two
  // values, so there is nothing else to keep in sync.
  function setFilter(key: "country" | "category", value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [stats, setStats] = useState<ProspectStats | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);

  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [citySuggestions, setCitySuggestions] = useState<CityAutocompleteResult[]>([]);
  const [showCitySuggestions, setShowCitySuggestions] = useState(false);
  // Groups the keystrokes of one "typing session" for Google's session-based
  // Autocomplete billing SKU — regenerated whenever a fresh session starts (after a
  // suggestion is picked, or the field is cleared), per Google's own guidance.
  const sessionTokenRef = useRef<string>(crypto.randomUUID());
  const cityDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [callAgentId, setCallAgentId] = useState<string>("");
  const [callNumber, setCallNumber] = useState("");
  const [callingId, setCallingId] = useState<string | null>(null);
  const [callFeedback, setCallFeedback] = useState<Record<string, string>>({});

  const [notesDraft, setNotesDraft] = useState("");
  const [savingNotes, setSavingNotes] = useState(false);

  const [importing, setImporting] = useState(false);
  const [importSummary, setImportSummary] = useState("");

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const fetchProspects = useCallback(async () => {
    const res = await api.get<Prospect[]>("/prospects");
    setProspects(res.data);
    // Counts come from their own aggregate endpoint rather than the fetched page, which
    // is capped at 100 rows. Fire-and-forget so a stats hiccup can't blank the list.
    api
      .get<ProspectStats>("/prospects/stats")
      .then((s) => setStats(s.data))
      .catch(() => {});
    return res.data;
  }, []);

  useEffect(() => {
    fetchProspects()
      .catch(() => setProspects([]))
      .finally(() => setLoading(false));

    api
      .get<Agent[]>("/agents")
      .then((res) => {
        setAgents(res.data);
        const retellAgent = res.data.find((a) => a.platform === "retell");
        if (retellAgent) setCallAgentId(retellAgent.id);
      })
      .catch(() => setAgents([]));
  }, [fetchProspects]);

  // While anything is still pending/running research, poll so rows flip to "KB ready" live.
  useEffect(() => {
    const hasInFlight = prospects.some(
      (p) => p.research_status === "pending" || p.research_status === "running",
    );
    if (hasInFlight && !pollRef.current) {
      pollRef.current = setInterval(() => {
        fetchProspects().catch(() => {});
      }, 4000);
    }
    if (!hasInFlight && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [prospects, fetchProspects]);

  async function runDiscovery() {
    setDiscovering(true);
    try {
      await api.post(
        "/prospects/discover",
        { query, location: location || null, radius_m: 20000, limit: 20 },
      );
      // Discovery + research run in the background — refresh shortly after to catch new rows.
      setTimeout(() => fetchProspects().catch(() => {}), 1500);
    } finally {
      setDiscovering(false);
    }
  }

  function onLocationChange(value: string) {
    setLocation(value);
    if (cityDebounceRef.current) clearTimeout(cityDebounceRef.current);

    if (value.trim().length < 2) {
      setCitySuggestions([]);
      setShowCitySuggestions(false);
      return;
    }

    cityDebounceRef.current = setTimeout(async () => {
      try {
        const res = await api.get<CityAutocompleteResponse>("/prospects/city-autocomplete", {
          params: { input: value, session_token: sessionTokenRef.current },
        });
        setCitySuggestions(res.data.suggestions);
        setShowCitySuggestions(true);
      } catch {
        // Suggestions are a convenience, not a requirement — a failed lookup just
        // means no dropdown, the operator can still type freely.
        setCitySuggestions([]);
      }
    }, 300);
  }

  function selectCitySuggestion(suggestion: CityAutocompleteResult) {
    setLocation(suggestion.label);
    setShowCitySuggestions(false);
    setCitySuggestions([]);
    // A suggestion was picked — the next autocomplete session (e.g. for the next
    // search) should bill as a new one, per Google's session-token guidance.
    sessionTokenRef.current = crypto.randomUUID();
  }

  async function importCsv(file: File) {
    setImporting(true);
    setImportSummary("");
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await api.post<CsvImportResult>("/prospects/import-csv", form);
      const { imported, skipped_duplicates, skipped_invalid, errors } = res.data;
      setImportSummary(
        `Imported ${imported} · ${skipped_duplicates} duplicate${skipped_duplicates === 1 ? "" : "s"} skipped · ` +
          `${skipped_invalid} invalid skipped${errors.length ? ` — ${errors.join("; ")}` : ""}`,
      );
      fetchProspects().catch(() => {});
    } catch (err) {
      setImportSummary(getApiErrorMessage(err, "Import failed."));
    } finally {
      setImporting(false);
      // Clear the input so re-picking the same file fires onChange again.
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function rerunResearch(id: string) {
    await api.post(`/prospects/${id}/research`);
    fetchProspects().catch(() => {});
  }

  async function setOutreach(id: string, outreach_status: OutreachStatus) {
    await api.patch(`/prospects/${id}`, { outreach_status });
    fetchProspects().catch(() => {});
  }

  async function setStatus(id: string, status: ProspectStatus) {
    // Optimistic: the dropdown is the operator's own input, so reflect it immediately
    // and let the refetch reconcile (or revert) it.
    setProspects((prev) => prev.map((p) => (p.id === id ? { ...p, status } : p)));
    try {
      await api.patch(`/prospects/${id}`, { status });
    } finally {
      fetchProspects().catch(() => {});
    }
  }

  function openCallPanel(prospect: Prospect) {
    setExpandedId(expandedId === prospect.id ? null : prospect.id);
    setCallNumber(prospect.phone || "");
    setNotesDraft(prospect.prospect_notes || "");
    setCallFeedback((prev) => ({ ...prev, [prospect.id]: "" }));
  }

  async function saveNotes(prospect: Prospect) {
    setSavingNotes(true);
    try {
      await api.patch(`/prospects/${prospect.id}`, { prospect_notes: notesDraft || null });
      setCallFeedback((prev) => ({ ...prev, [prospect.id]: "Notes saved." }));
      fetchProspects().catch(() => {});
    } catch (err) {
      setCallFeedback((prev) => ({
        ...prev,
        [prospect.id]: getApiErrorMessage(err, "Failed to save notes."),
      }));
    } finally {
      setSavingNotes(false);
    }
  }

  async function placeCall(prospect: Prospect) {
    if (!callAgentId || !callNumber) return;
    setCallingId(prospect.id);
    try {
      const res = await api.post(`/prospects/${prospect.id}/call`, {
        agent_id: callAgentId,
        to_number: callNumber,
      });
      setCallFeedback((prev) => ({
        ...prev,
        [prospect.id]: `Dialing from ${res.data.from_number} · call ${res.data.call_id.slice(0, 12)}…`,
      }));
      fetchProspects().catch(() => {});
    } catch (err) {
      const message = getApiErrorMessage(err, "Failed to place call.");
      setCallFeedback((prev) => ({ ...prev, [prospect.id]: message }));
    } finally {
      setCallingId(null);
    }
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

  const filteredProspects = prospects.filter((p) => {
    if (countryFilter && (p.country || UNSPECIFIED) !== countryFilter) return false;
    if (categoryFilter && (p.category || UNSPECIFIED) !== categoryFilter) return false;
    return true;
  });
  const grouped = groupProspects(filteredProspects);

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Prospects"
        subtitle="Discovery finds companies, research builds their knowledge base — you just pick who to call."
      />

      {stats && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
          {STAT_TILES.map(({ key, label }) => (
            <Card key={key} className="p-3">
              <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
              <p className="mt-0.5 text-2xl font-semibold tabular-nums text-slate-900">
                {stats[key]}
              </p>
            </Card>
          ))}
        </div>
      )}

      <Card className="mb-6 p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <Field label="What are you looking for">
            <TextInput
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="dentists, marketing agencies, gyms…"
            />
          </Field>
          <Field label="Where">
            <div className="relative">
              <TextInput
                value={location}
                onChange={(e) => onLocationChange(e.target.value)}
                onFocus={() => citySuggestions.length > 0 && setShowCitySuggestions(true)}
                onBlur={() => setTimeout(() => setShowCitySuggestions(false), 150)}
                placeholder="Berlin, Germany"
                autoComplete="off"
              />
              {showCitySuggestions && citySuggestions.length > 0 && (
                <ul className="absolute z-10 mt-1 w-full rounded-lg border border-slate-200 bg-white py-1 text-sm shadow-lg">
                  {citySuggestions.map((s) => (
                    <li key={s.place_id}>
                      <button
                        type="button"
                        // onMouseDown, not onClick: fires before the input's onBlur closes
                        // the dropdown, so the click actually lands on the option.
                        onMouseDown={() => selectCitySuggestion(s)}
                        className="block w-full px-3 py-1.5 text-left text-slate-700 hover:bg-slate-50"
                      >
                        {s.label}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
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

        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) importCsv(file);
            }}
          />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => fileRef.current?.click()}
            disabled={importing}
          >
            {importing ? "Importing…" : "Import CSV"}
          </Button>
          <span className="text-xs text-slate-400">
            Columns: business_name, phone (required) · city, country, source, niche
            (optional)
          </span>
        </div>

        {importSummary && <p className="mt-2 text-xs text-slate-600">{importSummary}</p>}
      </Card>

      {!loading && prospects.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <label className="text-xs font-medium text-slate-500">
            Country
            <select
              value={countryFilter}
              onChange={(e) => setFilter("country", e.target.value)}
              className="ml-2 rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 focus:border-brand-300 focus:outline-none"
            >
              <option value="">All countries</option>
              {countryOptions.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium text-slate-500">
            Category
            <select
              value={categoryFilter}
              onChange={(e) => setFilter("category", e.target.value)}
              className="ml-2 rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 focus:border-brand-300 focus:outline-none"
            >
              <option value="">All categories</option>
              {categoryOptions.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          {(countryFilter || categoryFilter) && (
            <Button variant="ghost" size="sm" onClick={() => router.replace(pathname)}>
              Clear filters
            </Button>
          )}
        </div>
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
          description="Try a different country or category, or clear the filters above."
        />
      ) : (
        <div className="space-y-8">
          {grouped.map((countryGroup) => (
            <div key={countryGroup.country}>
              <div className="mb-3 flex items-baseline gap-2 border-b border-slate-200 pb-1.5">
                <h2 className="text-base font-semibold text-slate-900">
                  {countryGroup.country}
                </h2>
                <span className="text-xs text-slate-400 tabular-nums">
                  ({countryGroup.count})
                </span>
              </div>

              <div className="space-y-5">
                {countryGroup.categories.map((categoryGroup) => (
                  <div key={categoryGroup.category}>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                      {categoryGroup.category}{" "}
                      <span className="tabular-nums text-slate-400">
                        ({categoryGroup.prospects.length})
                      </span>
                    </h3>

                    <div className="space-y-3">
                      {categoryGroup.prospects.map((prospect) => {
                        const research = RESEARCH_META[prospect.research_status];
                        const outreach = OUTREACH_META[prospect.outreach_status];
                        const ready = prospect.research_status === "ready";
                        const expanded = expandedId === prospect.id;

                        return (
                          <Card key={prospect.id} className="p-4">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2">
                                  <p className="truncate font-medium text-slate-900">
                                    {prospect.name}
                                  </p>
                                  <span className="text-xs text-slate-400 tabular-nums">
                                    priority {prospect.priority_score.toFixed(2)}
                                  </span>
                                </div>
                                <p className="mt-0.5 truncate text-xs text-slate-500">
                                  {[prospect.city, prospect.address].filter(Boolean).join(" · ") ||
                                    "—"}
                                  {prospect.rating != null &&
                                    ` · ★ ${prospect.rating} (${prospect.review_count})`}
                                </p>
                              </div>

                              <div className="flex items-center gap-2">
                                <Badge tone={research.tone}>{research.label}</Badge>
                                <Badge tone={outreach.tone}>{outreach.label}</Badge>

                                <select
                                  aria-label={`Status for ${prospect.name}`}
                                  value={prospect.status}
                                  onChange={(e) =>
                                    setStatus(prospect.id, e.target.value as ProspectStatus)
                                  }
                                  className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 focus:border-brand-300 focus:outline-none"
                                >
                                  {STATUS_ORDER.map((s) => (
                                    <option key={s} value={s}>
                                      {STATUS_LABELS[s]}
                                    </option>
                                  ))}
                                </select>

                                {prospect.research_status === "failed" && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    icon={<RefreshIcon width={14} height={14} />}
                                    onClick={() => rerunResearch(prospect.id)}
                                  >
                                    Retry
                                  </Button>
                                )}

                                <Button
                                  variant="secondary"
                                  size="sm"
                                  onClick={() => router.push(`/prospects/${prospect.id}/sandbox`)}
                                  disabled={!ready}
                                  title="Read how the call would go, over text — no phone call"
                                >
                                  Sandbox chat
                                </Button>

                                <Button
                                  variant={expanded ? "secondary" : "primary"}
                                  size="sm"
                                  onClick={() => openCallPanel(prospect)}
                                  disabled={!ready}
                                >
                                  Call
                                </Button>
                              </div>
                            </div>

                            {expanded && (
                              <div className="mt-4 border-t border-slate-100 pt-4">
                                {prospect.research.summary && (
                                  <div className="mb-4 rounded-lg bg-slate-50/70 p-3">
                                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                                      Knowledge base
                                    </p>
                                    <p className="text-sm text-slate-700">
                                      {prospect.research.summary}
                                    </p>
                                    {prospect.research.hooks.length > 0 && (
                                      <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-slate-500">
                                        {prospect.research.hooks.map((h) => (
                                          <li key={h}>{h}</li>
                                        ))}
                                      </ul>
                                    )}
                                  </div>
                                )}

                                <div className="mb-4">
                                  <label
                                    htmlFor={`notes-${prospect.id}`}
                                    className="mb-1.5 block text-sm font-medium text-slate-700"
                                  >
                                    Your notes
                                  </label>
                                  <textarea
                                    id={`notes-${prospect.id}`}
                                    value={notesDraft}
                                    onChange={(e) => setNotesDraft(e.target.value)}
                                    rows={3}
                                    placeholder="Anything the research missed — who answers the phone, when to call, what they said last time…"
                                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-brand-300 focus:outline-none"
                                  />
                                  <div className="mt-1.5 flex items-center gap-3">
                                    <Button
                                      variant="secondary"
                                      size="sm"
                                      onClick={() => saveNotes(prospect)}
                                      disabled={
                                        savingNotes ||
                                        notesDraft === (prospect.prospect_notes || "")
                                      }
                                    >
                                      {savingNotes ? "Saving…" : "Save notes"}
                                    </Button>
                                    <span className="text-xs text-slate-400">
                                      Spoken on the real call, and trusted over the knowledge
                                      base above.
                                    </span>
                                  </div>
                                </div>

                                <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                                  <div className="flex-1">
                                    <label className="mb-1.5 block text-sm font-medium text-slate-700">
                                      Call with agent
                                    </label>
                                    <select
                                      value={callAgentId}
                                      onChange={(e) => setCallAgentId(e.target.value)}
                                      className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-brand-300 focus:outline-none"
                                    >
                                      {retellAgents.length === 0 && (
                                        <option value="">No Retell agents yet</option>
                                      )}
                                      {retellAgents.map((a) => (
                                        <option key={a.id} value={a.id}>
                                          {a.name}
                                        </option>
                                      ))}
                                    </select>
                                  </div>
                                  <div className="flex-1">
                                    <label className="mb-1.5 block text-sm font-medium text-slate-700">
                                      Phone number
                                    </label>
                                    <TextInput
                                      value={callNumber}
                                      onChange={(e) => setCallNumber(e.target.value)}
                                      placeholder="+491701234567"
                                    />
                                  </div>
                                  <Button
                                    onClick={() => placeCall(prospect)}
                                    disabled={
                                      callingId === prospect.id || !callAgentId || !callNumber
                                    }
                                  >
                                    {callingId === prospect.id ? "Calling…" : "Place call"}
                                  </Button>
                                </div>

                                {callFeedback[prospect.id] && (
                                  <p className="mt-2 text-xs text-slate-500">
                                    {callFeedback[prospect.id]}
                                  </p>
                                )}

                                <div className="mt-3 flex gap-2">
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => setOutreach(prospect.id, "callback")}
                                  >
                                    Mark callback
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => setOutreach(prospect.id, "do_not_call")}
                                  >
                                    Do not call
                                  </Button>
                                </div>
                              </div>
                            )}
                          </Card>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
