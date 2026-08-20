"use client";

import { TextInput } from "@/components/ui";

/**
 * Editable inputs for the {{placeholders}} a platform agent's prompt declares (ADR-012).
 *
 * Every value is shown, including auto-suggested ones, because Retell substitutes these
 * into a script we can't see the rest of and then speaks the result to a real person —
 * so the operator must be able to read exactly what will be said before dialing. Blanks
 * are flagged here rather than only at the API, since finding out from a 422 after
 * clicking "Place call" is a worse way to learn the same thing.
 */
export function DynamicVariableFields({
  variables,
  values,
  onChange,
}: {
  variables: string[];
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
}) {
  if (variables.length === 0) return null;

  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50/60 p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
        Prompt variables
      </p>
      <p className="mt-1 text-xs text-slate-500">
        This agent&apos;s script in Retell uses these placeholders. They&apos;re spoken as
        written if left blank.
      </p>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {variables.map((name) => (
          <div key={name}>
            <label
              htmlFor={`var-${name}`}
              className="mb-1 block font-mono text-xs text-slate-600"
            >
              {`{{${name}}}`}
            </label>
            <TextInput
              id={`var-${name}`}
              value={values[name] ?? ""}
              onChange={(e) => onChange(name, e.target.value)}
              placeholder="Required"
              className={values[name]?.trim() ? undefined : "border-amber-300"}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
