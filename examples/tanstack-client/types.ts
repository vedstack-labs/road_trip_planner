// Hand-written types mirroring the API's Pydantic schemas.
//
// PREFERRED: replace this file with types generated from the live OpenAPI doc,
// which stay in sync automatically:
//
//   npx openapi-typescript $VITE_API_URL/openapi.json -o ./schema.d.ts
//
// then import e.g. `components["schemas"]["TripOut"]`.
//
// NOTE on casing: the API returns snake_case JSON everywhere EXCEPT the chat
// response, which serializes `conversationId` (camelCase alias).

export type Region = "australia" | "nepal";
export type TripDuration =
  | "1_hour"
  | "half_day"
  | "full_day"
  | "weekend"
  | "multi_day";
export type TravellerType = "solo" | "couple" | "family" | "friends";
export type Mood =
  | "nature"
  | "scenic"
  | "food"
  | "historical"
  | "beaches"
  | "adventure"
  | "relaxing"
  | "coffee"
  | "kids";
export type StopType =
  | "attraction"
  | "scenic_lookout"
  | "restaurant"
  | "cafe"
  | "rest_stop";
export type JourneyStatus = "planned" | "active" | "paused" | "completed";

// --- Agent ---
export interface ChatRequest {
  message: string;
  conversation_id?: string | null;
}
export interface ChatResponse {
  conversationId: string; // camelCase alias on the wire
  response: string;
}

// --- Trips ---
export interface StopInput {
  order?: number | null;
  place_name: string;
  stop_type?: StopType;
  latitude: number;
  longitude: number;
  description?: string | null;
  rating?: number | null;
  dwell_minutes?: number;
  arrival_time?: string | null;
  departure_time?: string | null;
}
export interface TripCreate {
  title: string;
  region?: Region;
  origin: string;
  destination: string;
  traveller_type: TravellerType;
  mood?: string[];
  duration: TripDuration;
  summary?: string | null;
  stops?: StopInput[];
}
export interface StopOut {
  id: string;
  order: number;
  place_name: string;
  stop_type: StopType;
  latitude: number;
  longitude: number;
  description: string | null;
  rating: number | null;
  dwell_minutes: number;
  arrival_time: string | null;
  departure_time: string | null;
}
export interface TripOut {
  id: string;
  title: string;
  region: Region;
  origin: string;
  destination: string;
  traveller_type: string;
  mood: string[];
  duration: string;
  summary: string | null;
  share_token: string | null;
  created_at: string;
  stops: StopOut[];
}
export interface TripListItem {
  id: string;
  title: string;
  region: Region;
  origin: string;
  destination: string;
  duration: string;
  created_at: string;
  stop_count: number;
}
export interface ShareResponse {
  trip_id: string;
  share_token: string;
  share_url: string;
}

// --- Journey ---
export interface JourneyStartRequest {
  trip_id: string;
}
export interface JourneyOut {
  id: string;
  trip_id: string;
  status: JourneyStatus;
  current_stop_index: number;
  roadside_reason: string | null;
  started_at: string | null;
  updated_at: string;
}
export interface JourneyProgress {
  journey_id: string;
  status: JourneyStatus;
  current_stop: string | null;
  next_attraction: string | null;
  next_restaurant: string | null;
  remaining_stops: number;
  remaining_drive_minutes: number;
}
