"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui";
import { CheckIcon } from "@/components/icons";

interface PromptEditorProps {
  initialValue: string;
  onSave: (value: string) => void | Promise<void>;
  // Fires on every keystroke, in addition to the editor's own internal state — lets a
  // parent track the live draft (e.g. the sandbox page, which sends it as a per-turn
  // system_prompt_override before it's ever saved).
  onChange?: (value: string) => void;
}

export function PromptEditor({ initialValue, onSave, onChange }: PromptEditorProps) {
  const [value, setValue] = useState(initialValue);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => setValue(initialValue), [initialValue]);

  const handleChange = (next: string) => {
    setValue(next);
    onChange?.(next);
  };

  const dirty = value !== initialValue;

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(value);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card">
      <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/60 px-4 py-2.5">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
          System prompt
        </span>
        <span className="text-xs tabular-nums text-slate-400">{value.length} chars</span>
      </div>
      <textarea
        value={value}
        onChange={(e) => handleChange(e.target.value)}
        rows={14}
        spellCheck={false}
        className="block w-full resize-y border-0 bg-white p-4 font-mono text-[13px] leading-relaxed text-slate-800 focus:outline-none focus:ring-0"
        placeholder="[ROLE] You are a voice assistant for..."
      />
      <div className="flex items-center justify-end gap-3 border-t border-slate-100 bg-slate-50/60 px-4 py-2.5">
        {saved && (
          <span className="flex items-center gap-1 text-xs font-medium text-emerald-600">
            <CheckIcon width={14} height={14} /> Saved
          </span>
        )}
        <Button onClick={handleSave} disabled={saving || !dirty} size="sm">
          {saving ? "Saving…" : "Save prompt"}
        </Button>
      </div>
    </div>
  );
}
