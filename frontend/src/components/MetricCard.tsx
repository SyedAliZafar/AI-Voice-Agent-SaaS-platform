import { ReactNode } from "react";

interface MetricCardProps {
  label: string;
  value: string | number;
  tone?: "default" | "success" | "warning";
  icon?: ReactNode;
  hint?: string;
}

const TONE_TEXT = {
  default: "text-slate-900",
  success: "text-emerald-600",
  warning: "text-amber-600",
} as const;

const TONE_CHIP = {
  default: "bg-brand-50 text-brand-600",
  success: "bg-emerald-50 text-emerald-600",
  warning: "bg-amber-50 text-amber-600",
} as const;

export function MetricCard({ label, value, tone = "default", icon, hint }: MetricCardProps) {
  return (
    <div className="card p-5 transition-shadow hover:shadow-card-hover">
      <div className="flex items-start justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
        {icon && (
          <span
            className={`flex h-8 w-8 items-center justify-center rounded-lg ${TONE_CHIP[tone]}`}
          >
            {icon}
          </span>
        )}
      </div>
      <p className={`mt-3 text-3xl font-semibold tracking-tight ${TONE_TEXT[tone]}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}
