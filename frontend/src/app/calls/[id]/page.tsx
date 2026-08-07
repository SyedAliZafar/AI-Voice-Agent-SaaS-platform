"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { TranscriptViewer } from "@/components/features/calls/TranscriptViewer";
import { ArrowLeftIcon } from "@/components/icons";
import { Card, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { CALL_STATUS_META, formatDuration, sentimentMeta } from "@/lib/format";
import { Call, Transcript } from "@/lib/types";

export default function CallDetailPage({ params }: { params: { id: string } }) {
  const [call, setCall] = useState<Call | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    api
      .get<Call>(`/calls/${params.id}`)
      .then((res) => setCall(res.data))
      .catch(() => setCall(null))
      .finally(() => setLoading(false));

    // Transcript may live on a sub-resource; degrade gracefully if unavailable.
    api
      .get<Transcript>(`/calls/${params.id}/transcript`)
      .then((res) => setTranscript(res.data))
      .catch(() => setTranscript(null));
  }, [params.id]);

  if (loading) {
    return (
      <div className="animate-fade-in">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="mt-4 h-24 w-full rounded-2xl" />
        <Skeleton className="mt-4 h-64 w-full rounded-2xl" />
      </div>
    );
  }

  if (!call) {
    return (
      <div className="animate-fade-in">
        <button
          onClick={() => router.push("/calls")}
          className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800"
        >
          <ArrowLeftIcon width={16} height={16} /> Back to calls
        </button>
        <Card className="p-10 text-center text-sm text-slate-500">Call not found.</Card>
      </div>
    );
  }

  const status = CALL_STATUS_META[call.status];
  const sentiment = sentimentMeta(call.sentiment_score);

  const stats = [
    { label: "Status", node: (
      <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${status.badge}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${status.dot}`} />
        {status.label}
      </span>
    ) },
    { label: "Duration", node: <span className="font-medium text-slate-900">{formatDuration(call.duration_sec)}</span> },
    { label: "Sentiment", node: (
      <span className="inline-flex items-center gap-2 text-sm text-slate-700">
        <span className={`h-2 w-2 rounded-full ${sentiment.color}`} />
        {sentiment.label}
      </span>
    ) },
    { label: "Started", node: <span className="font-medium text-slate-900">{new Date(call.started_at).toLocaleString()}</span> },
  ];

  return (
    <div className="animate-fade-in">
      <button
        onClick={() => router.push("/calls")}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800"
      >
        <ArrowLeftIcon width={16} height={16} /> Back to calls
      </button>

      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
        <span className="font-mono">{call.caller_number}</span>
      </h1>
      <p className="mt-1 text-sm text-slate-500">Call ID {call.id}</p>

      <div className="mt-5 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label} className="p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{s.label}</p>
            <div className="mt-2">{s.node}</div>
          </Card>
        ))}
      </div>

      <Card className="mt-6 p-5">
        <p className="mb-4 text-sm font-semibold text-slate-900">Transcript</p>
        <TranscriptViewer turns={transcript?.turns ?? []} />
      </Card>

      {transcript?.s3_audio_url && (
        <Card className="mt-4 p-5">
          <p className="mb-3 text-sm font-semibold text-slate-900">Recording</p>
          <audio controls src={transcript.s3_audio_url} className="w-full" />
        </Card>
      )}
    </div>
  );
}
