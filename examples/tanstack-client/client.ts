// Framework-agnostic fetch client: base URL, bearer auth, typed errors.
//
// Set VITE_API_URL (Vite) / NEXT_PUBLIC_API_URL (Next) to your Vercel API URL,
// e.g. https://your-app.vercel.app

// `import.meta.env` (Vite) isn't in the default lib types; assign the cast to a
// named const, then read `.env` off the typed value (no inline-cast access).
const meta = import.meta as unknown as { env?: Record<string, string | undefined> };
const viteEnv = meta.env;
const API_URL =
  viteEnv?.VITE_API_URL ??
  (typeof process !== "undefined" ? process.env.NEXT_PUBLIC_API_URL : undefined);

if (!API_URL) {
  throw new Error("Missing VITE_API_URL / NEXT_PUBLIC_API_URL");
}

export const BASE = `${API_URL}/api/v1`;

// Wire this to your auth store (see auth.ts). Return null when logged out.
// `getToken` is indirection over a mutable module-private binding, so it cannot
// be inlined at call sites.
let tokenGetter: () => string | null = () => null;
export function setTokenGetter(fn: () => string | null) {
  tokenGetter = fn;
}
export function getToken(): string | null {
  return tokenGetter();
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function errorDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = body.detail; // narrowed to unknown by the `in` check above
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return JSON.stringify(detail); // FastAPI 422 array
  }
  return fallback;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });

  if (!res.ok) {
    const body: unknown = await res.json().catch(() => undefined);
    throw new ApiError(res.status, errorDetail(body, res.statusText));
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}
