// Journey resource: query keys + typed request functions.
import { api } from "./client";
import type { JourneyOut, JourneyProgress } from "./types";

export const journeyKeys = {
  active: ["journey", "active"] as const,
  detail: (id: string) => ["journey", id] as const,
};

export const journeyApi = {
  start: (tripId: string) =>
    api<JourneyOut>("/journey/start", {
      method: "POST",
      body: JSON.stringify({ trip_id: tripId }),
    }),
  // Returns 404 when there is no active journey; callers decide how to handle.
  active: () => api<JourneyProgress>("/journey/active"),
  progress: (id: string) => api<JourneyProgress>(`/journey/${id}`),
  advance: (id: string) =>
    api<JourneyProgress>(`/journey/${id}/advance`, { method: "POST" }),
  resume: (id: string) =>
    api<JourneyOut>(`/journey/${id}/resume`, { method: "POST" }),
  complete: (id: string) =>
    api<JourneyOut>(`/journey/${id}/complete`, { method: "POST" }),
};
