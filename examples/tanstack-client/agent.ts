// Agent chat: one-shot request + Server-Sent-Events streaming over POST.
import { BASE, api, getToken } from "./client";
import type { ChatRequest, ChatResponse } from "./types";

export const chatKeys = {
  conversation: (id: string) => ["agent", "conversation", id] as const,
};

export const agentApi = {
  chat: (body: ChatRequest) =>
    api<ChatResponse>("/agent/chat", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

// Stream events emitted by POST /agent/chat/stream.
type StreamEvent =
  | { type: "delta"; text: string }
  | { type: "done"; conversation_id: string }
  | { type: "error"; message: string };

function parseEvent(raw: string): StreamEvent | null {
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object" || !("type" in value)) return null;
  const t = value.type;
  if (t === "delta" && "text" in value && typeof value.text === "string") {
    return { type: "delta", text: value.text };
  }
  if (
    t === "done" &&
    "conversation_id" in value &&
    typeof value.conversation_id === "string"
  ) {
    return { type: "done", conversation_id: value.conversation_id };
  }
  if (t === "error" && "message" in value && typeof value.message === "string") {
    return { type: "error", message: value.message };
  }
  return null;
}

// EventSource cannot POST or send Authorization headers, so stream with fetch +
// a ReadableStream reader and parse the `data: {json}\n\n` frames ourselves.
export async function streamChat(
  body: ChatRequest,
  onDelta: (text: string) => void,
  signal?: AbortSignal,
): Promise<{ conversationId: string }> {
  const res = await fetch(`${BASE}/agent/chat/stream`, {
    method: "POST",
    signal,
    headers: {
      "Content-Type": "application/json",
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    throw new Error(`stream failed: ${res.status} ${res.statusText}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let conversationId = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    const frames = buf.split("\n\n");
    buf = frames.pop() ?? ""; // keep the trailing partial frame

    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const evt = parseEvent(line.slice(5).trim());
      if (!evt) continue;
      if (evt.type === "delta") onDelta(evt.text);
      else if (evt.type === "done") conversationId = evt.conversation_id;
      else if (evt.type === "error") throw new Error(evt.message);
    }
  }
  return { conversationId };
}
