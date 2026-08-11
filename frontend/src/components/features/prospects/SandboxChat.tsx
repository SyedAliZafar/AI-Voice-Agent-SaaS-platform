"use client";

import { useEffect, useRef, useState } from "react";

import { RefreshIcon } from "@/components/icons";
import { Button, Card } from "@/components/ui";
import { SandboxMessage } from "@/lib/types";

export function SandboxChat({
  messages,
  sending,
  error,
  canChat,
  onSend,
  onReset,
}: {
  messages: SandboxMessage[];
  sending: boolean;
  error: string | null;
  canChat: boolean;
  onSend: (text: string) => void;
  onReset: () => void;
}) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  function submit() {
    const text = input.trim();
    if (!text) return;
    onSend(text);
    setInput("");
  }

  return (
    <Card className="flex h-[32rem] flex-col p-0 lg:col-span-2">
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-5">
        {messages.length === 0 ? (
          <p className="py-10 text-center text-sm text-slate-400">
            {canChat ? "Say something to start the conversation." : "Pick an agent to start."}
          </p>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-start" : "flex-row-reverse"}`}>
              <div
                className={`max-w-[80%] rounded-2xl px-3.5 py-2 text-sm ${
                  m.role === "user"
                    ? "rounded-tl-sm bg-slate-100 text-slate-800"
                    : "rounded-tr-sm bg-brand-600 text-white"
                }`}
              >
                {m.content}
              </div>
            </div>
          ))
        )}
        {sending && <p className="text-xs text-slate-400">Thinking…</p>}
      </div>
      {error && <p className="border-t border-slate-100 px-5 py-2 text-xs text-red-600">{error}</p>}
      <div className="flex items-center gap-2 border-t border-slate-100 p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          disabled={!canChat}
          placeholder={canChat ? "Type what the caller would say…" : "Pick an agent first…"}
          className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none disabled:opacity-50"
        />
        <Button size="sm" onClick={submit} disabled={!canChat || sending || !input.trim()}>
          {sending ? "Sending…" : "Send"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          icon={<RefreshIcon width={14} height={14} />}
          onClick={onReset}
          disabled={messages.length === 0 || sending}
          title="Clear the conversation"
        >
          Reset
        </Button>
      </div>
    </Card>
  );
}
