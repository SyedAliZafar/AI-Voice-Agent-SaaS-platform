"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/ui";
import { api, getApiErrorMessage } from "@/lib/api";
import { CsvImportResult } from "@/lib/types";

/** Secondary way to get prospects onto the board, alongside discovery — a header
 * action rather than a form field, so it doesn't compete with the primary search
 * flow. Columns: business_name, phone (required); city, country, source, niche
 * (optional).
 */
export function CsvImportButton({ onImported }: { onImported: () => void }) {
  const [importing, setImporting] = useState(false);
  const [summary, setSummary] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function importCsv(file: File) {
    setImporting(true);
    setSummary("");
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await api.post<CsvImportResult>("/prospects/import-csv", form);
      const { imported, skipped_duplicates, skipped_invalid, errors } = res.data;
      setSummary(
        `Imported ${imported} · ${skipped_duplicates} duplicate${skipped_duplicates === 1 ? "" : "s"} skipped · ` +
          `${skipped_invalid} invalid skipped${errors.length ? ` — ${errors.join("; ")}` : ""}`,
      );
      onImported();
    } catch (err) {
      setSummary(getApiErrorMessage(err, "Import failed."));
    } finally {
      setImporting(false);
      // Clear the input so re-picking the same file fires onChange again.
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="relative">
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
        title="Columns: business_name, phone (required) · city, country, source, niche (optional)"
      >
        {importing ? "Importing…" : "Import CSV"}
      </Button>
      {summary && (
        <p className="absolute right-0 top-full mt-1.5 w-64 text-right text-xs text-slate-500">
          {summary}
        </p>
      )}
    </div>
  );
}
