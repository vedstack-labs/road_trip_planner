// Trip resource: query keys + typed request functions.
import { api } from "./client";
import type {
  ShareResponse,
  TripCreate,
  TripListItem,
  TripOut,
} from "./types";

export const tripKeys = {
  all: ["trips"] as const,
  list: () => [...tripKeys.all, "list"] as const,
  detail: (id: string) => [...tripKeys.all, "detail", id] as const,
  shared: (token: string) => ["trips", "shared", token] as const,
};

export const tripsApi = {
  list: () => api<TripListItem[]>("/trips"),
  get: (id: string) => api<TripOut>(`/trips/${id}`),
  create: (body: TripCreate) =>
    api<TripOut>("/trips", { method: "POST", body: JSON.stringify(body) }),
  share: (id: string) =>
    api<ShareResponse>(`/trips/${id}/share`, { method: "POST" }),
  getShared: (token: string) => api<TripOut>(`/trips/shared/${token}`),
};
