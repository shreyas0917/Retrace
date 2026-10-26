const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/** Marker header the backend requires on cookie-authenticated writes (CSRF guard). */
const CONSOLE_HEADER = { "X-Requested-With": "retrace-console" } as const;

export { API_BASE };

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export type AuthState = {
  authenticated: boolean;
  method: "session" | "bearer" | null;
  expires_at: string | null;
};

function buildHeaders(apiKey?: string, json = true): HeadersInit {
  const headers: Record<string, string> = { ...CONSOLE_HEADER };
  if (json) headers["Content-Type"] = "application/json";
  // The console normally authenticates with the session cookie. A Bearer
  // header is only sent when a caller explicitly supplies a key.
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  return headers;
}

async function parseJson(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function errorMessage(body: unknown, status: number): string {
  return (
    (body as { error?: { message?: string } })?.error?.message ||
    `HTTP ${status}`
  );
}

export async function apiGet<T>(path: string, apiKey?: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: buildHeaders(apiKey),
    credentials: "include",
  });
  const body = await parseJson(res);
  if (!res.ok) throw new ApiError(errorMessage(body, res.status), res.status, body);
  return body as T;
}

export async function apiPost<T>(
  path: string,
  apiKey: string,
  payload: unknown,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: buildHeaders(apiKey),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  const body = await parseJson(res);
  if (!res.ok) throw new ApiError(errorMessage(body, res.status), res.status, body);
  return body as T;
}

export async function apiGetText(path: string): Promise<string> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: buildHeaders(undefined, false),
    credentials: "include",
  });
  const text = await res.text();
  if (!res.ok) {
    throw new ApiError(text || `HTTP ${res.status}`, res.status, text);
  }
  return text;
}

// --- Session auth -----------------------------------------------------------

export async function fetchAuthState(): Promise<AuthState> {
  return apiGet<AuthState>("/api/v1/auth/me");
}

/** Exchange the API key for an HttpOnly session cookie. The key is not kept. */
export async function login(apiKey: string): Promise<{
  authenticated: boolean;
  expires_at: string;
  ttl_seconds: number;
}> {
  return apiPost("/api/v1/auth/session", "", { api_key: apiKey });
}

export async function logout(): Promise<void> {
  await apiPost("/api/v1/auth/logout", "", {});
}
