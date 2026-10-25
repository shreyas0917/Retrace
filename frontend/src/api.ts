const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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

function authHeaders(apiKey: string): HeadersInit {
  return {
    Authorization: `Bearer ${apiKey}`,
    "Content-Type": "application/json",
  };
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

export async function apiGet<T>(
  path: string,
  apiKey?: string,
): Promise<T> {
  const headers: HeadersInit = apiKey
    ? authHeaders(apiKey)
    : { "Content-Type": "application/json" };
  const res = await fetch(`${API_BASE}${path}`, { headers });
  const body = await parseJson(res);
  if (!res.ok) {
    const msg =
      (body as { error?: { message?: string } })?.error?.message ||
      `HTTP ${res.status}`;
    throw new ApiError(msg, res.status, body);
  }
  return body as T;
}

export async function apiPost<T>(
  path: string,
  apiKey: string,
  payload: unknown,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: authHeaders(apiKey),
    body: JSON.stringify(payload),
  });
  const body = await parseJson(res);
  if (!res.ok) {
    const msg =
      (body as { error?: { message?: string } })?.error?.message ||
      `HTTP ${res.status}`;
    throw new ApiError(msg, res.status, body);
  }
  return body as T;
}

export async function apiGetText(path: string): Promise<string> {
  const res = await fetch(`${API_BASE}${path}`);
  const text = await res.text();
  if (!res.ok) {
    throw new ApiError(text || `HTTP ${res.status}`, res.status, text);
  }
  return text;
}
