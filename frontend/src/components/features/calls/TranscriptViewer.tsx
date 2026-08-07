import { TranscriptTurn } from "@/lib/types";

function formatTs(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function TranscriptViewer({ turns }: { turns: TranscriptTurn[] }) {
  if (turns.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-400">No transcript available.</p>
    );
  }

  return (
    <div className="space-y-4">
      {turns.map((turn, i) => {
        const isCaller = turn.role === "caller";
        return (
          <div key={i} className={`flex gap-2.5 ${isCaller ? "justify-start" : "flex-row-reverse"}`}>
            <div
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                isCaller ? "bg-slate-200 text-slate-600" : "bg-brand-100 text-brand-700"
              }`}
            >
              {isCaller ? "C" : "AI"}
            </div>
            <div className={`max-w-[75%] ${isCaller ? "items-start" : "items-end"} flex flex-col`}>
              <div
                className={`rounded-2xl px-3.5 py-2 text-sm ${
                  isCaller
                    ? "rounded-tl-sm bg-slate-100 text-slate-800"
                    : "rounded-tr-sm bg-brand-600 text-white"
                }`}
              >
                {turn.text}
              </div>
              <span className="mt-1 px-1 text-[11px] text-slate-400">
                {isCaller ? "Caller" : "Agent"} · {formatTs(turn.ts)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
