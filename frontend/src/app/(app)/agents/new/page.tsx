"use client";

import { Suspense } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { AgentBuilder } from "@/components/features/agents/AgentBuilder";
import { TemplateGallery } from "@/components/features/agents/TemplateGallery";
import { ArrowLeftIcon } from "@/components/icons";

/** useSearchParams() opts this whole tree out of static rendering unless wrapped in
 * Suspense — same reason /agents/page.tsx does this. */
export default function NewAgentPage() {
  return (
    <Suspense fallback={null}>
      <NewAgentPageInner />
    </Suspense>
  );
}

function NewAgentPageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Lives in the URL (like the /agents list's ?source=) so "start from a template" is
  // linkable and survives a refresh, rather than always defaulting to the AI wizard.
  const mode = searchParams.get("mode") === "custom" ? "custom" : "template";

  function setMode(next: "template" | "custom") {
    const params = new URLSearchParams(searchParams.toString());
    if (next === "template") params.delete("mode");
    else params.set("mode", next);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  return (
    <div className="animate-fade-in">
      <button
        onClick={() => router.push("/agents")}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800"
      >
        <ArrowLeftIcon width={16} height={16} /> Back to agents
      </button>

      <h1 className="mb-1 text-2xl font-semibold tracking-tight text-slate-900">
        {mode === "template" ? "Start from a template" : "Build a sales agent"}
      </h1>
      <p className="mb-6 text-sm text-slate-500">
        {mode === "template"
          ? "Pick who it's calling and what you're selling — the script is already written."
          : "Answer a few questions and the Strategist will write your outbound call playbook."}
      </p>

      <div className="mb-6 inline-flex rounded-xl bg-slate-100 p-1">
        {(
          [
            ["template", "Use a template"],
            ["custom", "Build custom"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            onClick={() => setMode(value)}
            className={
              mode === value
                ? "rounded-lg bg-white px-4 py-1.5 text-sm font-medium text-slate-900 shadow-sm"
                : "rounded-lg px-4 py-1.5 text-sm font-medium text-slate-500 hover:text-slate-700"
            }
          >
            {label}
          </button>
        ))}
      </div>

      {mode === "template" ? <TemplateGallery /> : <AgentBuilder />}
    </div>
  );
}
