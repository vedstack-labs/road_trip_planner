// Minimal token store. In production, set the token you received from the
// Helpsonroad identity service. In dev/staging, bootstrap one from the API's
// /auth/dev-token endpoint (available only when ENVIRONMENT != production).

import { api, setTokenGetter } from "./client";

const KEY = "hsr_token";
let token: string | null =
  typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;

export const authToken = {
  get: (): string | null => token,
  set: (t: string | null) => {
    token = t;
    if (typeof localStorage === "undefined") return;
    if (t) localStorage.setItem(KEY, t);
    else localStorage.removeItem(KEY);
  },
};

// Call once at app startup.
export function initAuth() {
  setTokenGetter(authToken.get);
}

// Dev/staging only: obtain a JWT from the API.
export async function fetchDevToken(
  userId = "dev-user",
): Promise<string> {
  const { access_token } = await api<{ access_token: string }>(
    "/auth/dev-token",
    { method: "POST", body: JSON.stringify({ user_id: userId }) },
  );
  authToken.set(access_token);
  return access_token;
}
