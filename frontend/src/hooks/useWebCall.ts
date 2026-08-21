"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { RetellWebClient } from "retell-client-js-sdk";

import { api, getApiErrorMessage } from "@/lib/api";
import { WebCallResponse, WebCallTurn } from "@/lib/types";

export type WebCallStatus = "idle" | "connecting" | "live" | "ended" | "error";

/** Which agent to talk to. The two kinds are genuinely different resources, not one
 * with an optional field: a local agent is a row we own and provision, a platform agent
 * lives in Retell's dashboard and can only be personalized through the `{{placeholders}}`
 * its own prompt declares (ADR-012). They post to different endpoints accordingly. */
export type WebCallTarget =
  | { kind: "local"; agentId: string }
  | {
      kind: "platform";
      externalAgentId: string;
      platform?: string;
      dynamicVariables?: Record<string, string>;
    };

/** Drives a browser-mic conversation with one agent.
 *
 * Audio runs browser<->Retell directly, so nothing here touches our websocket, needs a
 * tunnel, or spends telephony minutes — see backend/services/test_call_service.py's
 * place_web_call for why that matters for demos.
 *
 * The transcript arrives as Retell's `update` event, which re-sends the WHOLE
 * conversation each time rather than the latest turn. We therefore replace state on
 * every update instead of appending — appending would duplicate every turn on every
 * frame, which is the obvious-looking bug here.
 */
export function useWebCall(target: WebCallTarget | null) {
  const clientRef = useRef<RetellWebClient | null>(null);
  const [status, setStatus] = useState<WebCallStatus>("idle");
  const [turns, setTurns] = useState<WebCallTurn[]>([]);
  const [agentTalking, setAgentTalking] = useState(false);
  const [callId, setCallId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // One client for the hook's lifetime. Constructing it per call would leak the
  // previous instance's LiveKit room and its event listeners.
  if (clientRef.current === null && typeof window !== "undefined") {
    clientRef.current = new RetellWebClient();
  }

  useEffect(() => {
    const client = clientRef.current;
    if (!client) return;

    const onStarted = () => setStatus("live");
    const onEnded = () => {
      setStatus("ended");
      setAgentTalking(false);
    };
    const onAgentStart = () => setAgentTalking(true);
    const onAgentStop = () => setAgentTalking(false);
    const onUpdate = (update: { transcript?: WebCallTurn[] }) => {
      if (Array.isArray(update?.transcript)) setTurns(update.transcript);
    };
    const onError = (err: unknown) => {
      setError(typeof err === "string" ? err : "The call dropped. Check mic permissions.");
      setStatus("error");
      client.stopCall();
    };

    client.on("call_started", onStarted);
    client.on("call_ended", onEnded);
    client.on("agent_start_talking", onAgentStart);
    client.on("agent_stop_talking", onAgentStop);
    client.on("update", onUpdate);
    client.on("error", onError);

    return () => {
      client.off("call_started", onStarted);
      client.off("call_ended", onEnded);
      client.off("agent_start_talking", onAgentStart);
      client.off("agent_stop_talking", onAgentStop);
      client.off("update", onUpdate);
      client.off("error", onError);
      // Hanging up on unmount is deliberate: navigating away must not leave a live,
      // billed call running with no UI attached to end it.
      client.stopCall();
    };
  }, []);

  const start = useCallback(async () => {
    const client = clientRef.current;
    if (!client || !target) return;

    setStatus("connecting");
    setError(null);
    setTurns([]);
    try {
      const res =
        target.kind === "local"
          ? await api.post<WebCallResponse>(`/agents/${target.agentId}/web-call`)
          : await api.post<WebCallResponse>("/agents/platform/web-call", {
              external_agent_id: target.externalAgentId,
              platform: target.platform ?? "retell",
              dynamic_variables: target.dynamicVariables,
            });
      setCallId(res.data.call_id);
      await client.startCall({ accessToken: res.data.access_token });
    } catch (err) {
      // A rejected mic permission surfaces here too, not as an SDK "error" event.
      setError(
        getApiErrorMessage(err, "Could not start the call. Allow microphone access and retry."),
      );
      setStatus("error");
    }
    // Serialized because `target` is rebuilt inline by callers on every render; comparing
    // by identity would make `start` a new function each time and defeat the memo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(target)]);

  const stop = useCallback(() => {
    clientRef.current?.stopCall();
    setStatus("ended");
  }, []);

  return { status, turns, agentTalking, callId, error, start, stop };
}
