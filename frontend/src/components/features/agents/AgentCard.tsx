import { Agent } from "@/lib/types";

const PLATFORM_META: Record<Agent["platform"], { label: string; badge: string }> = {
  retell: { label: "Retell AI", badge: "bg-brand-50 text-brand-700" },
  vapi: { label: "Vapi AI", badge: "bg-violet-50 text-violet-700" },
};

export function AgentCard({ agent, onClick }: { agent: Agent; onClick?: () => void }) {
  const platform = PLATFORM_META[agent.platform];
  const initial = agent.name.trim().charAt(0).toUpperCase() || "A";

  return (
    <button
      onClick={onClick}
      className="card group w-full p-5 text-left transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-sm font-semibold text-white">
            {initial}
          </div>
          <div className="min-w-0">
            <p className="truncate font-semibold text-slate-900">{agent.name}</p>
            <span
              className={`mt-0.5 inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${platform.badge}`}
            >
              {platform.label}
            </span>
          </div>
        </div>
        <span className="flex items-center gap-1.5 text-xs text-emerald-600">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Active
        </span>
      </div>

      <p className="mt-4 line-clamp-2 min-h-[2.5rem] text-sm text-slate-500">
        {agent.system_prompt || "No system prompt configured yet."}
      </p>

      <p className="mt-3 text-xs font-medium text-brand-600 opacity-0 transition-opacity group-hover:opacity-100">
        Open agent →
      </p>
    </button>
  );
}
