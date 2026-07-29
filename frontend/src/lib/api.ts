import axios from "axios";

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api",
});

// The backend derives tenant_id from this token (backend/api/deps.py) — it is no longer
// passed as a query param. Until a real login flow exists, mint one with
// `uv run python scripts/dev_token.py` and put it in frontend/.env.local as
// NEXT_PUBLIC_DEV_AUTH_TOKEN; a value in localStorage always wins over it.
api.interceptors.request.use((config) => {
  const stored = typeof window !== "undefined" ? localStorage.getItem("auth_token") : null;
  const token = stored || process.env.NEXT_PUBLIC_DEV_AUTH_TOKEN;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// FastAPI returns `detail` as a string for HTTPExceptions but as an array of
// {type, loc, msg, input, ctx} objects for 422 validation errors. Flatten either
// shape into a readable string so callers never store/render the raw object.
export function getApiErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((e) => (e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : ""))
      .filter(Boolean);
    if (msgs.length) return msgs.join(", ");
  }
  return fallback;
}
