// React hooks binding the resource layer to TanStack Query.
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useState } from "react";
import { agentApi, streamChat } from "./agent";
import { ApiError } from "./client";
import { journeyApi, journeyKeys } from "./journey";
import { tripKeys, tripsApi } from "./trips";
import type { ChatRequest, JourneyProgress } from "./types";

// --- Trips ---
export function useTrips() {
  return useQuery({ queryKey: tripKeys.list(), queryFn: tripsApi.list });
}

export function useTrip(id: string) {
  return useQuery({
    queryKey: tripKeys.detail(id),
    queryFn: () => tripsApi.get(id),
    enabled: !!id,
  });
}

export function useCreateTrip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: tripsApi.create,
    onSuccess: (trip) => {
      qc.setQueryData(tripKeys.detail(trip.id), trip);
      qc.invalidateQueries({ queryKey: tripKeys.list() });
    },
  });
}

export function useShareTrip(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => tripsApi.share(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: tripKeys.detail(id) }),
  });
}

// --- Journey ---
// Maps the API's 404 ("no active journey") to null instead of an error state.
export function useActiveJourney() {
  return useQuery<JourneyProgress | null>({
    queryKey: journeyKeys.active,
    queryFn: async () => {
      try {
        return await journeyApi.active();
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    retry: false,
  });
}

export function useJourney(id: string) {
  return useQuery({
    queryKey: journeyKeys.detail(id),
    queryFn: () => journeyApi.progress(id),
    enabled: !!id,
  });
}

// advance / resume / complete all change both the specific journey and the
// "active" view, so invalidate both.
function useJourneyTransition(
  id: string,
  action: (id: string) => Promise<unknown>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => action(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: journeyKeys.detail(id) });
      qc.invalidateQueries({ queryKey: journeyKeys.active });
    },
  });
}

export const useAdvanceJourney = (id: string) =>
  useJourneyTransition(id, journeyApi.advance);
export const useResumeJourney = (id: string) =>
  useJourneyTransition(id, journeyApi.resume);
export const useCompleteJourney = (id: string) =>
  useJourneyTransition(id, journeyApi.complete);

export function useStartJourney() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tripId: string) => journeyApi.start(tripId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: journeyKeys.active }),
  });
}

// --- Agent chat ---
export function useChat() {
  return useMutation({ mutationFn: (body: ChatRequest) => agentApi.chat(body) });
}

// Streaming chat: accumulates deltas into `text` and exposes send()/streaming.
export function useChatStream() {
  const [text, setText] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function send(message: string) {
    setText("");
    setError(null);
    setStreaming(true);
    try {
      const { conversationId: cid } = await streamChat(
        { message, conversation_id: conversationId },
        (delta) => setText((prev) => prev + delta),
      );
      setConversationId(cid);
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setStreaming(false);
    }
  }

  return { text, conversationId, streaming, error, send };
}
