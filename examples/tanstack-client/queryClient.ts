// QueryClient factory. Create one per app (browser) or per request (SSR).
import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./client";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Retry transient 5xx only; never retry 4xx (auth/validation/not-found).
        retry: (count, error) =>
          !(error instanceof ApiError && error.status < 500) && count < 2,
      },
    },
  });
}
