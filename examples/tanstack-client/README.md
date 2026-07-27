# TanStack client (drop-in)

Framework-agnostic TypeScript modules for consuming this API from a web app
built with [TanStack Query](https://tanstack.com/query) (v5), optionally with
[TanStack Router / Start](https://tanstack.com/router). Copy this folder into
your frontend's `src/api/` and wire it up — nothing here depends on the Python
backend at build time.

## Files

| File | Purpose |
|---|---|
| `client.ts` | `fetch` wrapper: base URL, bearer auth, typed `ApiError`. |
| `auth.ts` | Token store + `initAuth()`; `fetchDevToken()` for dev/staging. |
| `types.ts` | Hand-written types mirroring the Pydantic schemas (see "Types" below). |
| `trips.ts` / `journey.ts` / `agent.ts` | Query keys + typed request functions per resource. |
| `queryClient.ts` | `QueryClient` factory (retry policy: 5xx only). |
| `hooks.ts` | React hooks: `useTrips`, `useCreateTrip`, `useActiveJourney`, `useChatStream`, … |

## Setup

```bash
npm i @tanstack/react-query
```

```ts
// env: VITE_API_URL=https://<your-app>.vercel.app   (or NEXT_PUBLIC_API_URL)

// 1. At app startup:
import { initAuth } from "./api/auth";
initAuth();

// 2. Wrap the tree:
import { QueryClientProvider } from "@tanstack/react-query";
import { createQueryClient } from "./api/queryClient";
const queryClient = createQueryClient();
// <QueryClientProvider client={queryClient}>…</QueryClientProvider>
```

Auth token:
- **Production** — set the JWT from the Helpsonroad identity service:
  `authToken.set(jwtFromIdentityService)`.
- **Dev/staging** — `await fetchDevToken()` (calls `/auth/dev-token`, which is
  disabled in production).

Global 401 handling: catch `ApiError` with `status === 401`, call
`authToken.set(null)`, and redirect to login.

## Usage

```tsx
import { useTrips, useCreateTrip, useChatStream } from "./api/hooks";

function Trips() {
  const { data, isLoading } = useTrips();
  const create = useCreateTrip();
  // create.mutate({ title, region, origin, destination, traveller_type, duration });
}

function Chat() {
  const { text, streaming, send } = useChatStream();
  // <button onClick={() => send("Plan a weekend from Sydney")} disabled={streaming} />
}
```

## Types

`types.ts` is hand-written and accurate to the current schemas, but the
maintainable path is to generate from the live OpenAPI document so types stay in
sync automatically:

```bash
npx openapi-typescript $VITE_API_URL/openapi.json -o ./schema.d.ts
```

Then swap the imports for `components["schemas"]["TripOut"]`, etc.

## Notes

- JSON is **snake_case** everywhere **except** the chat response, which returns
  `conversationId` (camelCase). `types.ts` reflects this.
- `GET /journey/active` returns **404** when there is no active journey;
  `useActiveJourney` maps that to `null`.
- Streaming (`agent.ts` `streamChat`) uses `fetch` + `ReadableStream`, not
  `EventSource` (which can't POST or send an `Authorization` header). Long agent
  turns are bounded by your Vercel function's max duration — fall back to the
  non-streaming `useChat` if you hit it.
