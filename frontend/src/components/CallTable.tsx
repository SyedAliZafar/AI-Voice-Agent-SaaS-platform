"use client";

import { useRouter } from "next/navigation";

import { CALL_STATUS_META, formatDuration, sentimentMeta } from "@/lib/format";
import { Call } from "@/lib/types";

export function CallTable({ calls }: { calls: Call[] }) {
  const router = useRouter();

  if (calls.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-slate-400">No calls to show yet.</div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-100 text-left text-xs font-medium uppercase tracking-wide text-slate-400">
            <th className="py-2.5 pr-2 font-medium">Caller</th>
            <th className="py-2.5 px-2 font-medium">Status</th>
            <th className="py-2.5 px-2 font-medium">Sentiment</th>
            <th className="py-2.5 pl-2 text-right font-medium">Duration</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((call) => {
            const status = CALL_STATUS_META[call.status];
            const sentiment = sentimentMeta(call.sentiment_score);
            return (
              <tr
                key={call.id}
                onClick={() => router.push(`/calls/${call.id}`)}
                className="cursor-pointer border-b border-slate-50 transition-colors last:border-0 hover:bg-slate-50/70"
              >
                <td className="py-3 pr-2 font-mono text-[13px] text-slate-700">
                  {call.caller_number}
                </td>
                <td className="py-3 px-2">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${status.badge}`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${status.dot}`} />
                    {status.label}
                  </span>
                </td>
                <td className="py-3 px-2">
                  <span className="inline-flex items-center gap-2 text-xs text-slate-500">
                    <span className={`h-2 w-2 rounded-full ${sentiment.color}`} />
                    {sentiment.label}
                  </span>
                </td>
                <td className="py-3 pl-2 text-right tabular-nums text-slate-600">
                  {formatDuration(call.duration_sec)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
